"""
Purchase order endpoint tests.

Routes exercised:
  POST   /api/purchase
  GET    /api/purchase
  PUT    /api/purchase/<id>
  DELETE /api/purchase/<id>
  PUT    /api/purchase/<id>/cancel
"""

import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import purchase_payload
from tests.helpers.db_helpers import execute, fetch_one, get_product_stock


pytestmark = pytest.mark.purchase


@pytest.fixture
def test_purchase_order(client, admin_headers, test_product, test_supplier):
    """Create a purchase order and clean up after the test."""
    payload = purchase_payload(
        test_supplier["supplier_id"],
        test_product["product_id"],
    )
    resp = client.post("/api/purchase", json=payload, headers=admin_headers)
    assert resp.status_code == 201, f"Purchase fixture failed: {resp.data}"
    order = parse_json(resp)
    yield order
    po_id = order.get("purchase_order_id") or order.get("id")
    if po_id:
        execute("DELETE FROM purchase_order_items WHERE purchase_order_id=%s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE purchase_order_id=%s", (po_id,))


# ── POST /api/purchase ────────────────────────────────────────────────────────

class TestCreatePurchaseOrder:

    def test_admin_can_create_purchase_order(self, client, admin_headers, test_product, test_supplier):
        payload = purchase_payload(test_supplier["supplier_id"], test_product["product_id"])
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert "purchase_order_id" in data or "id" in data
        po_id = data.get("purchase_order_id") or data.get("id")
        execute("DELETE FROM purchase_order_items WHERE purchase_order_id=%s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE purchase_order_id=%s", (po_id,))

    def test_cashier_cannot_create_purchase_order(self, client, cashier_headers, test_product, test_supplier):
        payload = purchase_payload(test_supplier["supplier_id"], test_product["product_id"])
        resp = client.post("/api/purchase", json=payload, headers=cashier_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_create_purchase_order(self, client, test_product, test_supplier):
        payload = purchase_payload(test_supplier["supplier_id"], test_product["product_id"])
        resp = client.post("/api/purchase", json=payload)
        assert resp.status_code == 401

    def test_stock_increases_after_purchase(self, client, admin_headers, test_product, test_supplier):
        pid = test_product["product_id"]
        stock_before = get_product_stock(pid)
        payload = purchase_payload(test_supplier["supplier_id"], pid)
        payload["items"][0]["quantity"] = 10
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        assert get_product_stock(pid) == stock_before + 10
        po_id = (parse_json(resp).get("purchase_order_id") or parse_json(resp).get("id"))
        execute("DELETE FROM purchase_order_items WHERE purchase_order_id=%s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE purchase_order_id=%s", (po_id,))

    def test_empty_items_returns_400(self, client, admin_headers, test_supplier):
        payload = {
            "supplier_id": test_supplier["supplier_id"],
            "purchase_order_number": f"PO-{uid8()}",
            "items": [],
        }
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_duplicate_purchase_order_number_returns_error(self, client, admin_headers, test_purchase_order, test_product, test_supplier):
        po_number = (
            test_purchase_order.get("purchase_order_number")
            or fetch_one(
                "SELECT purchase_order_number FROM purchase_orders WHERE purchase_order_id=%s",
                (test_purchase_order.get("purchase_order_id"),),
            )["purchase_order_number"]
        )
        payload = purchase_payload(test_supplier["supplier_id"], test_product["product_id"])
        payload["purchase_order_number"] = po_number
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code in (400, 409, 500)

    def test_nonexistent_supplier_returns_error(self, client, admin_headers, test_product):
        payload = purchase_payload(999999999, test_product["product_id"])
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code in (400, 404, 500)

    def test_missing_supplier_id_returns_error(self, client, admin_headers, test_product):
        payload = {
            "purchase_order_number": f"PO-{uid8()}",
            "items": [{"product_id": test_product["product_id"], "quantity": 1, "purchase_rate": 80.0, "gst_rate": 18.0}],
        }
        resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert resp.status_code in (400, 422, 500)

    def test_empty_body_returns_error(self, client, admin_headers):
        resp = client.post("/api/purchase", json=None, headers=admin_headers)
        assert resp.status_code in (400, 422, 500)


# ── GET /api/purchase ─────────────────────────────────────────────────────────

class TestGetPurchaseOrders:

    def test_admin_can_list_purchase_orders(self, client, admin_headers):
        resp = client.get("/api/purchase", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(parse_json(resp), list)

    def test_cashier_cannot_list_purchase_orders(self, client, cashier_headers):
        resp = client.get("/api/purchase", headers=cashier_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list_purchase_orders(self, client):
        resp = client.get("/api/purchase")
        assert resp.status_code == 401

    def test_created_order_appears_in_list(self, client, admin_headers, test_purchase_order):
        resp = client.get("/api/purchase", headers=admin_headers)
        orders = parse_json(resp)
        po_id = test_purchase_order.get("purchase_order_id") or test_purchase_order.get("id")
        ids = [o.get("purchase_order_id") or o.get("id") for o in orders]
        assert po_id in ids


# ── PUT /api/purchase/<id>/cancel ─────────────────────────────────────────────

class TestCancelPurchaseOrder:

    def test_admin_can_cancel_purchase_order(self, client, admin_headers, test_product, test_supplier):
        payload = purchase_payload(test_supplier["supplier_id"], test_product["product_id"])
        create_resp = client.post("/api/purchase", json=payload, headers=admin_headers)
        assert create_resp.status_code == 201
        data = parse_json(create_resp)
        po_id = data.get("purchase_order_id") or data.get("id")

        cancel_resp = client.put(f"/api/purchase/{po_id}/cancel", headers=admin_headers)
        assert cancel_resp.status_code == 200

        row = fetch_one("SELECT status FROM purchase_orders WHERE purchase_order_id=%s", (po_id,))
        assert row["status"] == "Cancelled"

    def test_cancel_nonexistent_order_returns_404(self, client, admin_headers):
        resp = client.put("/api/purchase/999999999/cancel", headers=admin_headers)
        assert resp.status_code == 404

    def test_cashier_cannot_cancel_purchase_order(self, client, cashier_headers, test_purchase_order):
        po_id = test_purchase_order.get("purchase_order_id") or test_purchase_order.get("id")
        resp = client.put(f"/api/purchase/{po_id}/cancel", headers=cashier_headers)
        assert resp.status_code == 403
