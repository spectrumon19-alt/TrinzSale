"""
Sales invoice API tests — validates GST calculation math, stock management,
invoice/receipt number format, cancel workflow, and documents BUG-006.
"""

import re
import time
import pytest
from tests.conftest import parse_json, uid8

pytestmark = pytest.mark.sales


# ── GST Calculation Validation ────────────────────────────────────────────────

class TestGSTCalculation:
    """
    Business rule (from calculate_invoice_item in routes/sales.py):
        total_line = qty * selling_rate           (GST-inclusive)
        exclusive  = total_line / (1 + gst/100)  (ex-GST base)
        total_gst  = total_line - exclusive
        sgst = cgst = total_gst / 2
    """

    @pytest.mark.parametrize("qty,rate,gst_rate,expected_line,expected_gst,expected_sgst", [
        (1,  100.00, 18.0, 100.00, 15.25, 7.63),  # ₹100 @ 18%
        (2,  50.00,  12.0,  100.00, 10.71, 5.36),  # ₹50 × 2 @ 12%
        (5,  200.00,  5.0, 1000.00, 47.62, 23.81),  # ₹200 × 5 @ 5%
        (1,  500.00,  0.0,  500.00,  0.00, 0.00),   # GST-exempt item
    ])
    def test_gst_formula_matches_inclusive_rate_model(
        self, client, cashier_headers, test_product, db_conn,
        qty, rate, gst_rate, expected_line, expected_gst, expected_sgst
    ):
        # Update product to match the test parameters
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE products SET selling_rate=%s, gst_rate=%s WHERE product_id=%s",
            (rate, gst_rate, test_product["product_id"])
        )
        db_conn.commit()

        resp = client.post("/api/sales", json={
            "customer_name": "GST Test Customer",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": qty,
                       "selling_rate": rate, "gst_rate": gst_rate}],
            "discount_percentage": 0,
        }, headers=cashier_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        items = data.get("items", [])
        assert len(items) == 1
        item = items[0]

        assert abs(float(item["total_line_amount"]) - expected_line) < 0.05, (
            f"total_line_amount: expected {expected_line}, got {item['total_line_amount']}"
        )
        assert abs(float(item["sgst"]) - expected_sgst) < 0.05, (
            f"SGST: expected {expected_sgst}, got {item['sgst']}"
        )
        assert abs(float(item["cgst"]) - float(item["sgst"])) < 0.01, (
            "SGST and CGST must always be equal"
        )

    def test_grand_total_documents_bug006_double_gst(self, client, cashier_headers, test_product, db_conn):
        """
        BUG-006 (Open): grand_total = total_amount + total_gst double-counts GST
        because total_amount is already GST-inclusive.

        For 1 unit at ₹100 (18% GST):
          total_amount = 100.00  (GST-inclusive)
          total_gst    = 15.25
          grand_total  = 115.25  ← WRONG — should be 100.00
        """
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE products SET selling_rate=100.0, gst_rate=18.0 WHERE product_id=%s",
            (test_product["product_id"],)
        )
        cur.execute(
            "UPDATE inventory SET stock_quantity=20 WHERE product_id=%s",
            (test_product["product_id"],)
        )
        db_conn.commit()

        resp = client.post("/api/sales", json={
            "customer_name": "BUG006 Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": 100.0, "gst_rate": 18.0}],
        }, headers=cashier_headers)
        assert resp.status_code == 201
        data = parse_json(resp)

        total_amount = float(data["total_amount"])
        total_gst    = float(data["total_gst"])
        grand_total  = float(data.get("grand_total", total_amount))

        # Document the bug: grand_total is inflated
        if abs(grand_total - (total_amount + total_gst)) < 0.01:
            pytest.xfail(
                "BUG-006 confirmed: grand_total double-counts GST. "
                f"total_amount={total_amount}, total_gst={total_gst}, "
                f"grand_total={grand_total} (should be {total_amount})"
            )
        # If grand_total == total_amount, the bug is fixed
        assert abs(grand_total - total_amount) < 0.01, (
            f"Once fixed: grand_total ({grand_total}) should equal total_amount ({total_amount})"
        )

    def test_rebate_reduces_total_line_amount(self, client, cashier_headers, test_product, db_conn):
        # Per-item discounts are now a flat ₹ REBATE off the line total (the old
        # per-item 'discount' % was replaced); GST is recomputed on the reduced
        # figure. ₹20 rebate on a ₹200 line → ₹180.
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE products SET selling_rate=200.0, gst_rate=18.0 WHERE product_id=%s",
            (test_product["product_id"],)
        )
        cur.execute(
            "UPDATE inventory SET stock_quantity=20 WHERE product_id=%s",
            (test_product["product_id"],)
        )
        db_conn.commit()

        resp = client.post("/api/sales", json={
            "customer_name": "Rebate Customer",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": 200.0, "gst_rate": 18.0, "rebate": 20}],
        }, headers=cashier_headers)
        assert resp.status_code == 201
        item = parse_json(resp)["items"][0]
        # ₹20 rebate on ₹200 → ₹180 line amount
        assert abs(float(item["total_line_amount"]) - 180.0) < 0.10, (
            f"₹20 rebate on ₹200 should give ₹180, got {item['total_line_amount']}"
        )
        # The stored rebate must round-trip
        assert abs(float(item.get("rebate_amount", 0)) - 20.0) < 0.01


# ── Stock Management ──────────────────────────────────────────────────────────

class TestStockManagement:

    def test_sale_decrements_inventory_by_exact_quantity(self, client, cashier_headers, test_product, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        stock_before = cur.fetchone()[0]

        resp = client.post("/api/sales", json={
            "customer_name": "Stock Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 3,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        assert resp.status_code == 201
        db_conn.commit()

        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        stock_after = cur.fetchone()[0]
        assert stock_before - stock_after == 3, (
            f"Stock must decrease by exactly 3: was {stock_before}, now {stock_after}"
        )

    def test_cancel_sale_restores_stock_exactly(self, client, admin_headers, cashier_headers, test_product, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        stock_before = cur.fetchone()[0]

        # Create sale
        sale_resp = client.post("/api/sales", json={
            "customer_name": "Cancel Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 5,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        assert sale_resp.status_code == 201
        invoice_id = parse_json(sale_resp)["invoice_id"]

        db_conn.commit()
        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        stock_after_sale = cur.fetchone()[0]
        assert stock_before - stock_after_sale == 5

        # Cancel
        cancel_resp = client.put(f"/api/sales/{invoice_id}/cancel", headers=admin_headers)
        assert cancel_resp.status_code == 200
        db_conn.commit()

        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        stock_after_cancel = cur.fetchone()[0]
        assert stock_after_cancel == stock_before, (
            f"Cancel must fully restore stock: before={stock_before}, "
            f"after_cancel={stock_after_cancel}"
        )

    def test_sale_exceeding_stock_returns_400(self, client, cashier_headers, test_product, db_conn):
        cur = db_conn.cursor()
        # Set stock to exactly 2
        cur.execute("UPDATE inventory SET stock_quantity=2 WHERE product_id=%s", (test_product["product_id"],))
        db_conn.commit()

        resp = client.post("/api/sales", json={
            "customer_name": "Oversell Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 10,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        assert resp.status_code == 400, (
            "Selling more than available stock must return 400 INSUFFICIENT_STOCK"
        )
        data = parse_json(resp)
        msg = (data.get("message") or "").lower()
        assert "stock" in msg or "insufficient" in msg

    def test_stock_not_modified_on_failed_sale(self, client, cashier_headers, test_product, db_conn):
        cur = db_conn.cursor()
        cur.execute("UPDATE inventory SET stock_quantity=1 WHERE product_id=%s", (test_product["product_id"],))
        db_conn.commit()

        # Attempt sale of 100 units (exceeds stock)
        client.post("/api/sales", json={
            "customer_name": "Rollback Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 100,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        db_conn.commit()

        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id=%s", (test_product["product_id"],))
        assert cur.fetchone()[0] == 1, "Failed sale must not modify inventory"


# ── Invoice & Receipt Number Format ──────────────────────────────────────────

class TestInvoiceNumberFormat:

    # Current format: D{DD}P{DDD}{YYMMDD} — the underscore was deliberately
    # removed from invoice numbers (e.g. D01P012260711).
    INVOICE_PATTERN = re.compile(r"D\d{2}P\d{3}\d{6}")
    RECEIPT_PATTERN = re.compile(r"R\d{8}\d{3}")

    def test_invoice_number_matches_format(self, client, cashier_headers, test_product):
        resp = client.post("/api/sales", json={
            "customer_name": "Format Test", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        inv_num = data.get("invoice_number", "")
        assert self.INVOICE_PATTERN.match(inv_num), (
            f"Invoice number '{inv_num}' must match D{{DD}}P{{DDD}}_{{YYMMDD}}"
        )

    def test_receipt_number_matches_format(self, client, cashier_headers, test_product):
        resp = client.post("/api/sales", json={
            "customer_name": "Receipt Format Test", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        rcpt = data.get("receipt_number", "")
        assert self.RECEIPT_PATTERN.match(rcpt), (
            f"Receipt number '{rcpt}' must match R{{YYYYMMDD}}{{NNN}}"
        )

    def test_receipt_sequence_increments_within_same_day(self, client, cashier_headers, test_product, db_conn):
        """Two sales on same day must get consecutive receipt sequence numbers."""
        cur = db_conn.cursor()
        cur.execute("UPDATE inventory SET stock_quantity=20 WHERE product_id=%s", (test_product["product_id"],))
        db_conn.commit()

        def make_sale():
            r = client.post("/api/sales", json={
                "customer_name": "Seq Test", "mode_of_payment": "Cash",
                "items": [{"product_id": test_product["product_id"], "quantity": 1,
                           "selling_rate": test_product["selling_rate"],
                           "gst_rate": test_product["gst_rate"]}],
            }, headers=cashier_headers)
            assert r.status_code == 201
            return parse_json(r)["receipt_number"]

        r1 = make_sale()
        r2 = make_sale()
        # Format RYYYYMMDDNNN — the daily sequence is the trailing 3 digits.
        seq1 = int(r1[-3:])
        seq2 = int(r2[-3:])
        assert seq2 == seq1 + 1, f"Receipt sequences must be consecutive: {r1}, {r2}"


# ── Cancel Invoice ────────────────────────────────────────────────────────────

class TestCancelInvoice:

    def test_cancel_sets_status_cancelled_in_db(self, client, admin_headers, cashier_headers, test_product, db_conn):
        sale_resp = client.post("/api/sales", json={
            "customer_name": "Cancel DB Test", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        invoice_id = parse_json(sale_resp)["invoice_id"]

        client.put(f"/api/sales/{invoice_id}/cancel", headers=admin_headers)
        db_conn.commit()

        cur = db_conn.cursor()
        cur.execute("SELECT status FROM sales_invoices WHERE invoice_id=%s", (invoice_id,))
        assert cur.fetchone()[0] == "Cancelled"

    def test_cancel_already_cancelled_returns_400(self, client, admin_headers, cashier_headers, test_product):
        sale_resp = client.post("/api/sales", json={
            "customer_name": "Double Cancel", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        invoice_id = parse_json(sale_resp)["invoice_id"]
        client.put(f"/api/sales/{invoice_id}/cancel", headers=admin_headers)

        resp = client.put(f"/api/sales/{invoice_id}/cancel", headers=admin_headers)
        assert resp.status_code == 400, "Cancelling an already-cancelled invoice must return 400"

    def test_cashier_cannot_cancel_invoice(self, client, cashier_headers, test_product):
        sale_resp = client.post("/api/sales", json={
            "customer_name": "Auth Cancel Test", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1,
                       "selling_rate": test_product["selling_rate"],
                       "gst_rate": test_product["gst_rate"]}],
        }, headers=cashier_headers)
        invoice_id = parse_json(sale_resp)["invoice_id"]

        resp = client.put(f"/api/sales/{invoice_id}/cancel", headers=cashier_headers)
        assert resp.status_code == 403, "Cashier must not be able to cancel invoices"

    def test_cancel_nonexistent_invoice_returns_404(self, client, admin_headers):
        resp = client.put("/api/sales/999999999/cancel", headers=admin_headers)
        assert resp.status_code == 404


# ── Input Validation ──────────────────────────────────────────────────────────

class TestSaleValidation:

    def test_sale_with_empty_items_returns_400(self, client, cashier_headers):
        resp = client.post("/api/sales", json={
            "customer_name": "Empty Items", "mode_of_payment": "Cash", "items": [],
        }, headers=cashier_headers)
        assert resp.status_code == 400

    def test_sale_without_items_returns_400(self, client, cashier_headers):
        resp = client.post("/api/sales", json={
            "customer_name": "No Items", "mode_of_payment": "Cash",
        }, headers=cashier_headers)
        assert resp.status_code == 400

    def test_sale_with_nonexistent_product_returns_error(self, client, cashier_headers):
        resp = client.post("/api/sales", json={
            "customer_name": "Ghost Product", "mode_of_payment": "Cash",
            "items": [{"product_id": 999999999, "quantity": 1,
                       "selling_rate": 100.0, "gst_rate": 18.0}],
        }, headers=cashier_headers)
        assert resp.status_code in (400, 500)

    def test_unauthenticated_sale_returns_401(self, client, test_product):
        resp = client.post("/api/sales", json={
            "customer_name": "Unauth", "mode_of_payment": "Cash",
            "items": [{"product_id": test_product["product_id"], "quantity": 1}],
        })
        assert resp.status_code == 401

    def test_get_invoice_by_id_returns_full_data(self, client, admin_headers, test_sale):
        invoice_id = test_sale["invoice_id"]
        resp = client.get(f"/api/sales/{invoice_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["invoice_id"] == invoice_id
        assert data["invoice_number"] is not None
        assert data["receipt_number"] is not None
        assert isinstance(data["items"], list) and len(data["items"]) > 0

    def test_get_nonexistent_invoice_returns_404(self, client, admin_headers):
        resp = client.get("/api/sales/999999999", headers=admin_headers)
        assert resp.status_code == 404
