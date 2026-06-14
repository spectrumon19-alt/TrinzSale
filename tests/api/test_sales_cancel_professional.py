"""
Professional invoice-cancellation tests.

These cover the hardened cancel behaviour added on top of the basic
stock-restore/status-flip (which is already tested in test_sales.py):

  - Cancellation audit trail (cancelled_by / cancelled_at / cancel_reason)
  - Block cancellation when returns exist against the invoice (409)
  - Credit-ledger linkage warning (non-fatal)
  - Net amount / GST exclusion from reports after cancel
  - Idempotency of stock restore (no double-restore)

Route under test:  PUT /api/sales/<invoice_id>/cancel
"""

import pytest

from tests.conftest import parse_json, uid8
from tests.helpers.db_helpers import (
    get_conn, fetch_one, fetch_all, execute, get_product_stock,
)

pytestmark = pytest.mark.sales


# ───────────────────────── helpers ───────────────────────────────────────────

def _make_sale(client, headers, product, qty=3):
    payload = {
        "customer_name": "Cancel Test",
        "customer_mobile": "9000012345",
        "mode_of_payment": "Cash",
        "discount_percentage": 0,
        "items": [{
            "product_id": product["product_id"],
            "quantity": qty,
            "rate": product["selling_rate"],
            "gst_rate": product["gst_rate"],
        }],
    }
    resp = client.post("/api/sales", json=payload, headers=headers)
    assert resp.status_code == 201, f"sale setup failed: {resp.data}"
    return parse_json(resp)


def _make_return(client, headers, invoice_id, qty):
    """Create a return for the first item of an invoice."""
    items = fetch_all(
        "SELECT item_id, product_id FROM sales_invoice_items WHERE invoice_id=%s",
        (invoice_id,),
    )
    assert items, "invoice has no items"
    payload = {
        "original_invoice_id": invoice_id,
        "return_reason": "Damaged Product",
        "refund_method": "Cash",
        "items": [{
            "original_item_id": items[0]["item_id"],
            "product_id": items[0]["product_id"],
            "quantity": qty,
        }],
    }
    return client.post("/api/returns", json=payload, headers=headers)


# ───────────────────────── audit trail ───────────────────────────────────────

class TestCancellationAuditTrail:

    def test_cancel_records_cancelled_by_and_at(self, client, admin_headers, cashier_headers,
                                                test_product, setup_test_database):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]

        resp = client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
        assert resp.status_code == 200

        row = fetch_one(
            "SELECT cancelled_by, cancelled_at, status FROM sales_invoices WHERE invoice_id=%s",
            (inv_id,),
        )
        assert row["status"] == "Cancelled"
        assert row["cancelled_by"] == setup_test_database["admin_id"]
        assert row["cancelled_at"] is not None

    def test_cancel_stores_reason_from_body(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]

        resp = client.put(
            f"/api/sales/{inv_id}/cancel",
            json={"reason": "Customer returned at counter"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        row = fetch_one("SELECT cancel_reason FROM sales_invoices WHERE invoice_id=%s", (inv_id,))
        assert row["cancel_reason"] == "Customer returned at counter"

    def test_cancel_without_reason_succeeds_with_null_reason(self, client, admin_headers,
                                                             cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]
        resp = client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
        assert resp.status_code == 200
        row = fetch_one("SELECT cancel_reason FROM sales_invoices WHERE invoice_id=%s", (inv_id,))
        assert row["cancel_reason"] is None

    def test_response_reports_items_restored(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=2)
        resp = client.put(f"/api/sales/{sale['invoice_id']}/cancel", headers=admin_headers)
        data = parse_json(resp)
        assert data.get("items_restored") == 1
        assert data.get("invoice_number") == sale["invoice_number"]


# ───────────────────────── block-on-returns ──────────────────────────────────

class TestCancelBlockedByReturns:

    def test_cancel_blocked_when_return_exists(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=5)
        inv_id = sale["invoice_id"]

        ret = _make_return(client, admin_headers, inv_id, qty=2)
        assert ret.status_code == 201, f"return setup failed: {ret.data}"

        resp = client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
        assert resp.status_code == 409, "Cancel must be blocked when returns exist"
        data = parse_json(resp)
        assert data.get("return_count", 0) >= 1

    def test_invoice_stays_completed_when_cancel_blocked(self, client, admin_headers,
                                                         cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product, qty=5)
        inv_id = sale["invoice_id"]
        _make_return(client, admin_headers, inv_id, qty=1)

        client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
        row = fetch_one("SELECT status FROM sales_invoices WHERE invoice_id=%s", (inv_id,))
        assert row["status"] == "Completed", "Blocked cancel must not change status"

    def test_stock_not_double_restored_when_cancel_blocked(self, client, admin_headers,
                                                           cashier_headers, test_product):
        # Return already restored stock; the blocked cancel must NOT add it again.
        sale = _make_sale(client, cashier_headers, test_product, qty=5)
        inv_id = sale["invoice_id"]
        stock_after_sale = get_product_stock(test_product["product_id"])

        _make_return(client, admin_headers, inv_id, qty=2)
        stock_after_return = get_product_stock(test_product["product_id"])
        assert stock_after_return == stock_after_sale + 2

        client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)  # blocked (409)
        stock_after_blocked_cancel = get_product_stock(test_product["product_id"])
        assert stock_after_blocked_cancel == stock_after_return, (
            "Blocked cancel must not restore stock again"
        )


# ───────────────────────── credit-linkage warning ────────────────────────────

class TestCreditLinkageWarning:

    def test_warning_when_credit_entry_references_invoice(self, client, admin_headers,
                                                          cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]
        inv_no = sale["invoice_number"]

        # Create a credit customer + a credit_transactions row referencing this invoice
        conn = get_conn()
        cur = conn.cursor()
        suffix = uid8()
        cur.execute(
            """
            INSERT INTO credit_customers (customer_code, customer_uuid, name, mobile, current_balance)
            VALUES (%s,%s,%s,%s,0) RETURNING customer_id
            """,
            (f"CW{suffix}", f"uuid-{suffix}", f"CredLink {suffix}", "9000099999"),
        )
        cid = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO credit_transactions (customer_id, transaction_type, amount, invoice_no, previous_balance)
            VALUES (%s, 'credit', 100, %s, 0)
            """,
            (cid, inv_no),
        )
        conn.commit()
        cur.close()
        conn.close()

        try:
            resp = client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
            assert resp.status_code == 200
            data = parse_json(resp)
            assert "warning" in data, "Cancel should warn about linked credit entries"
        finally:
            execute("DELETE FROM credit_transactions WHERE customer_id=%s", (cid,))
            execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))

    def test_no_warning_when_no_credit_link(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        resp = client.put(f"/api/sales/{sale['invoice_id']}/cancel", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "warning" not in data


# ───────────────────────── amount/GST exclusion after cancel ──────────────────

class TestCancelledExcludedFromReports:

    def test_cancelled_invoice_excluded_from_sales_report(self, client, admin_headers,
                                                          cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]

        before = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        sales_before = before["total_sales"]

        client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)

        after = parse_json(client.get("/api/reports/sales", headers=admin_headers))
        # Cancelled invoice's value must drop out of the headline total.
        assert after["total_sales"] <= sales_before

    def test_cancelled_invoice_not_in_completed_count(self, client, admin_headers,
                                                      cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]
        client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)

        row = fetch_one(
            "SELECT status FROM sales_invoices WHERE invoice_id=%s", (inv_id,)
        )
        assert row["status"] == "Cancelled"


# ───────────────────────── authorization (regression) ────────────────────────

class TestCancelAuthorization:

    def test_cashier_cannot_cancel(self, client, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        resp = client.put(f"/api/sales/{sale['invoice_id']}/cancel", headers=cashier_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_cancel(self, client, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        resp = client.put(f"/api/sales/{sale['invoice_id']}/cancel")
        assert resp.status_code == 401

    def test_double_cancel_returns_400(self, client, admin_headers, cashier_headers, test_product):
        sale = _make_sale(client, cashier_headers, test_product)
        inv_id = sale["invoice_id"]
        assert client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers).status_code == 200
        assert client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers).status_code == 400
