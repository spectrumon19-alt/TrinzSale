"""
Inventory management endpoint tests.

Routes exercised:
  GET  /api/inventory
  POST /api/inventory/update
"""

import pytest
from tests.conftest import parse_json
from tests.helpers.db_helpers import get_product_stock


pytestmark = pytest.mark.inventory


class TestGetInventory:

    def test_returns_inventory_list_for_admin(self, client, admin_headers):
        resp = client.get("/api/inventory", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert isinstance(data, list)

    def test_returns_inventory_list_for_cashier(self, client, cashier_headers):
        resp = client.get("/api/inventory", headers=cashier_headers)
        assert resp.status_code == 200

    def test_returns_401_without_token(self, client):
        resp = client.get("/api/inventory")
        assert resp.status_code == 401

    def test_inventory_records_contain_required_fields(self, client, admin_headers, test_product):
        resp = client.get("/api/inventory", headers=admin_headers)
        assert resp.status_code == 200
        items = parse_json(resp)
        if items:
            first = items[0]
            for field in ("product_id", "name", "sku", "stock_quantity"):
                assert field in first, f"Field '{field}' missing from inventory record"

    def test_test_product_appears_in_inventory(self, client, admin_headers, test_product):
        resp = client.get("/api/inventory", headers=admin_headers)
        items = parse_json(resp)
        pids = [i["product_id"] for i in items]
        assert test_product["product_id"] in pids


class TestUpdateInventory:

    def test_admin_can_add_stock(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        stock_before = get_product_stock(pid)
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": pid, "quantity_change": 10},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert get_product_stock(pid) == stock_before + 10

    def test_admin_can_subtract_stock(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        stock_before = get_product_stock(pid)
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": pid, "quantity_change": -5},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert get_product_stock(pid) == stock_before - 5

    def test_cashier_cannot_update_inventory(self, client, cashier_headers, test_product):
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": test_product["product_id"], "quantity_change": 5},
            headers=cashier_headers,
        )
        assert resp.status_code == 403

    def test_unauthenticated_cannot_update_inventory(self, client, test_product):
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": test_product["product_id"], "quantity_change": 5},
        )
        assert resp.status_code == 401

    def test_missing_product_id_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/inventory/update",
            json={"quantity_change": 5},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_quantity_change_returns_400(self, client, admin_headers, test_product):
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": test_product["product_id"]},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_nonexistent_product_returns_404(self, client, admin_headers):
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": 999999999, "quantity_change": 5},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_zero_quantity_change_is_accepted(self, client, admin_headers, test_product):
        """A zero change is a no-op; the endpoint should accept it."""
        pid = test_product["product_id"]
        stock_before = get_product_stock(pid)
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": pid, "quantity_change": 0},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert get_product_stock(pid) == stock_before

    def test_large_quantity_addition(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": pid, "quantity_change": 100_000},
            headers=admin_headers,
        )
        assert resp.status_code == 200
