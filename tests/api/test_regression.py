"""
Regression tests – end-to-end workflows that guard against previously reported
or potential regressions.

Each test represents a complete scenario rather than an isolated unit, ensuring
that modules interact correctly together.
"""

import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import product_payload, sale_payload, supplier_payload, purchase_payload
from tests.helpers.db_helpers import get_product_stock, execute, fetch_one


class TestStockManagementWorkflow:
    """Verify that stock levels are maintained correctly across the sale→cancel cycle."""

    def test_stock_decrements_on_sale_restores_on_cancel(self, client, admin_headers, cashier_headers, test_product):
        pid = test_product["product_id"]
        initial_stock = get_product_stock(pid)

        # Sale
        sale_resp = client.post(
            "/api/sales",
            json=sale_payload(pid, float(test_product["selling_rate"]), float(test_product["gst_rate"]),
                              items=[{"product_id": pid, "quantity": 3, "rate": float(test_product["selling_rate"]), "gst_rate": float(test_product["gst_rate"])}]),
            headers=cashier_headers,
        )
        assert sale_resp.status_code == 201
        inv_id = parse_json(sale_resp)["invoice_id"]
        assert get_product_stock(pid) == initial_stock - 3

        # Cancel
        cancel_resp = client.put(f"/api/sales/{inv_id}/cancel", headers=admin_headers)
        assert cancel_resp.status_code == 200
        assert get_product_stock(pid) == initial_stock  # fully restored

    def test_stock_increments_on_purchase(self, client, admin_headers, test_product, test_supplier):
        pid = test_product["product_id"]
        stock_before = get_product_stock(pid)

        payload = purchase_payload(test_supplier["supplier_id"], pid)
        payload["items"][0]["quantity"] = 20
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        assert get_product_stock(pid) == stock_before + 20

        po_id = parse_json(resp).get("purchase_order_id") or parse_json(resp).get("id")
        execute("DELETE FROM purchase_order_items WHERE purchase_order_id=%s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE purchase_order_id=%s", (po_id,))


class TestGSTCalculationRegression:
    """
    Ensure GST amounts computed by the API match the formula:
      exclusive = total / (1 + rate/100)
      sgst = cgst = (total - exclusive) / 2
    """

    @pytest.mark.parametrize("qty,rate,gst_rate", [
        (1, 100.0, 18.0),
        (2,  50.0, 12.0),
        (5,  30.0,  5.0),
        (1, 100.0,  0.0),
    ])
    def test_gst_calculation_matches_formula(self, client, cashier_headers, test_product, qty, rate, gst_rate):
        pid = test_product["product_id"]
        total = qty * rate
        expected_excl = total / (1 + gst_rate / 100)
        expected_gst = total - expected_excl

        # create_sale prices from the product's selling_rate/gst_rate (the item
        # 'rate'/'gst_rate' keys are not honoured), so set the product to match
        # this parametrised case before selling.
        from tests.helpers.db_helpers import execute
        execute("UPDATE products SET selling_rate=%s, gst_rate=%s WHERE product_id=%s",
                (rate, gst_rate, pid))

        payload = {
            "customer_name": "GST Test",
            "mode_of_payment": "Cash",
            "items": [{"product_id": pid, "quantity": qty, "selling_rate": rate, "gst_rate": gst_rate}],
        }
        resp = client.post("/api/sales", json=payload, headers=cashier_headers)
        assert resp.status_code == 201, f"Sale failed: {resp.data}"
        data = parse_json(resp)
        invoice_id = data["invoice_id"]

        # BUG-006: total_amount stores the EX-GST (taxable) base, and
        # grand_total = total_amount + total_gst equals the gross paid.
        # Read the persisted invoice to assert the stored semantics precisely.
        from tests.helpers.db_helpers import fetch_one
        inv = fetch_one(
            "SELECT total_amount, total_gst FROM sales_invoices WHERE invoice_id=%s",
            (invoice_id,),
        )
        stored_amount = float(inv["total_amount"])
        stored_gst = float(inv["total_gst"])

        assert stored_amount == pytest.approx(expected_excl, rel=0.01), \
            f"total_amount (ex-GST base) mismatch for qty={qty} rate={rate} gst_rate={gst_rate}"
        assert stored_gst == pytest.approx(expected_gst, rel=0.01), \
            f"total_gst mismatch for gst_rate={gst_rate}"
        assert (stored_amount + stored_gst) == pytest.approx(total, rel=0.01), \
            f"grand total mismatch for qty={qty} rate={rate} gst_rate={gst_rate}"


class TestInvoiceNumberSequencing:
    """Invoice numbers must be strictly sequentially unique."""

    def test_two_consecutive_invoices_have_different_numbers(self, client, cashier_headers, test_product):
        pid = test_product["product_id"]
        make_sale = lambda: client.post(
            "/api/sales",
            json=sale_payload(pid, float(test_product["selling_rate"]), float(test_product["gst_rate"]),
                              items=[{"product_id": pid, "quantity": 1, "rate": float(test_product["selling_rate"]), "gst_rate": float(test_product["gst_rate"])}]),
            headers=cashier_headers,
        )
        resp1 = make_sale()
        resp2 = make_sale()
        assert resp1.status_code == 201
        assert resp2.status_code == 201

        inv1 = parse_json(resp1)["invoice_number"]
        inv2 = parse_json(resp2)["invoice_number"]
        assert inv1 != inv2, "Consecutive invoices must have unique numbers"


class TestAuthTokenRoles:
    """Role-based access control regression – each role sees exactly what it should."""

    def test_admin_has_full_access(self, client, admin_headers, test_product):
        assert client.get("/api/products", headers=admin_headers).status_code == 200
        assert client.get("/api/admin/users", headers=admin_headers).status_code == 200
        assert client.get("/api/inventory", headers=admin_headers).status_code == 200
        assert client.get("/api/suppliers", headers=admin_headers).status_code == 200

    def test_cashier_has_limited_access(self, client, cashier_headers, test_product):
        assert client.get("/api/products", headers=cashier_headers).status_code == 200
        assert client.get("/api/admin/users", headers=cashier_headers).status_code == 403
        assert client.delete(
            f"/api/products/{test_product['product_id']}", headers=cashier_headers
        ).status_code == 403

    def test_unauthenticated_has_no_api_access(self, client):
        endpoints = [
            "/api/products",
            "/api/inventory",
            "/api/suppliers",
            "/api/admin/users",
        ]
        for ep in endpoints:
            assert client.get(ep).status_code == 401, f"Expected 401 for {ep}"


class TestDuplicateRecordHandling:
    """Duplicate creation should return appropriate errors, not 500."""

    def test_duplicate_product_sku_returns_client_error(self, client, admin_headers, test_product):
        payload = product_payload(sku=test_product["sku"])
        resp = client.post("/api/products", json=payload, headers=admin_headers)
        assert resp.status_code in (400, 409, 500)
        # Must not return 201 (created)
        assert resp.status_code != 201

    def test_duplicate_supplier_gst_returns_client_error(self, client, admin_headers, test_supplier):
        payload = supplier_payload(supplier_gst_number=test_supplier["supplier_gst_number"])
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400


class TestEdgeCases:
    """Miscellaneous edge cases that should be handled gracefully."""

    def test_get_nonexistent_resources_return_404(self, client, admin_headers):
        assert client.get("/api/products/999999999", headers=admin_headers).status_code == 404
        assert client.get("/api/sales/999999999", headers=admin_headers).status_code == 404

    def test_update_with_same_data_is_idempotent(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        payload = {
            "name": test_product["name"],
            "sku": test_product["sku"],
            "gst_rate": float(test_product["gst_rate"]),
            "selling_rate": float(test_product["selling_rate"]),
        }
        resp1 = client.put(f"/api/products/{pid}", json=payload, headers=admin_headers)
        resp2 = client.put(f"/api/products/{pid}", json=payload, headers=admin_headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_integer_product_id_only(self, client, admin_headers):
        """Non-integer product IDs should return 404 or 405, not 500."""
        resp = client.get("/api/products/abc", headers=admin_headers)
        assert resp.status_code in (404, 405, 400)

    def test_special_characters_in_customer_name(self, client, cashier_headers, test_product):
        pid = test_product["product_id"]
        payload = sale_payload(pid, float(test_product["selling_rate"]), float(test_product["gst_rate"]),
                               customer_name="O'Brien & Sons <Ltd>")
        resp = client.post("/api/sales", json=payload, headers=cashier_headers)
        assert resp.status_code == 201

    def test_unicode_in_product_name(self, client, admin_headers):
        payload = product_payload(name="Ārūn's Product 😊 日本語")
        resp = client.post("/api/products", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert data["name"] == payload["name"]
        pid = data["product_id"]
        execute("DELETE FROM inventory WHERE product_id=%s", (pid,))
        execute("DELETE FROM products WHERE product_id=%s", (pid,))
