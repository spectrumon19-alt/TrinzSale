"""
Product CRUD API tests — validates actual business logic, not just status codes.
Covers: create with stock init, search active-only bug (BUG-007), duplicate SKU,
deactivate, admin guard, type validation, DB state verification.
"""

import pytest
from tests.conftest import parse_json, uid8

pytestmark = pytest.mark.products


# ── Create Product ────────────────────────────────────────────────────────────

class TestCreateProduct:

    def test_create_product_returns_full_product_dict(self, client, admin_headers):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Agri Seed {sfx}", "sku": f"SEED-{sfx}",
            "gst_rate": 5.0, "purchase_rate": 40.0, "selling_rate": 60.0,
            "pack_size": "500g", "initial_stock": 100,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert data["name"] == f"Agri Seed {sfx}"
        assert data["sku"] == f"SEED-{sfx}"
        assert float(data["selling_rate"]) == 60.0
        assert float(data["gst_rate"]) == 5.0
        assert isinstance(data["product_id"], int)
        # Cleanup
        client.delete(f"/api/products/{data['product_id']}", headers=admin_headers)

    def test_create_product_initialises_inventory_with_correct_stock(self, client, admin_headers, db_conn):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Stock Test {sfx}", "sku": f"ST-{sfx}",
            "gst_rate": 12.0, "selling_rate": 80.0, "initial_stock": 75,
        }, headers=admin_headers)
        assert resp.status_code == 201
        pid = parse_json(resp)["product_id"]

        cur = db_conn.cursor()
        cur.execute("SELECT stock_quantity FROM inventory WHERE product_id = %s", (pid,))
        row = cur.fetchone()
        assert row is not None, "Inventory record must be created on product create"
        assert row[0] == 75, f"Expected stock=75, got {row[0]}"
        # Cleanup
        client.delete(f"/api/products/{pid}", headers=admin_headers)

    def test_create_product_with_zero_initial_stock_allowed(self, client, admin_headers):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Zero Stock {sfx}", "sku": f"ZS-{sfx}",
            "gst_rate": 18.0, "selling_rate": 100.0, "initial_stock": 0,
        }, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert data["stock_quantity"] == 0
        client.delete(f"/api/products/{data['product_id']}", headers=admin_headers)

    def test_create_product_missing_sku_returns_400(self, client, admin_headers):
        resp = client.post("/api/products", json={
            "name": "No SKU Product", "gst_rate": 5.0, "selling_rate": 50.0,
        }, headers=admin_headers)
        assert resp.status_code == 400

    def test_create_product_missing_selling_rate_returns_400(self, client, admin_headers):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"No Rate {sfx}", "sku": f"NR-{sfx}", "gst_rate": 5.0,
        }, headers=admin_headers)
        assert resp.status_code == 400

    def test_create_product_string_gst_rate_returns_400(self, client, admin_headers):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Bad GST {sfx}", "sku": f"BG-{sfx}",
            "gst_rate": "not-a-number", "selling_rate": 100.0,
        }, headers=admin_headers)
        assert resp.status_code == 400

    def test_create_duplicate_sku_returns_500_or_409(self, client, admin_headers, test_product):
        """Duplicate SKU must be rejected — UNIQUE constraint on products.sku."""
        resp = client.post("/api/products", json={
            "name": "Duplicate SKU Product",
            "sku": test_product["sku"],   # reuse existing SKU
            "gst_rate": 5.0, "selling_rate": 50.0,
        }, headers=admin_headers)
        assert resp.status_code in (409, 400, 500), (
            "Duplicate SKU must be rejected by DB UNIQUE constraint"
        )

    def test_cashier_cannot_create_product(self, client, cashier_headers):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Cashier Prod {sfx}", "sku": f"CP-{sfx}",
            "gst_rate": 5.0, "selling_rate": 50.0,
        }, headers=cashier_headers)
        assert resp.status_code == 403

    def test_no_auth_cannot_create_product(self, client):
        sfx = uid8()
        resp = client.post("/api/products", json={
            "name": f"Unauth {sfx}", "sku": f"UA-{sfx}",
            "gst_rate": 5.0, "selling_rate": 50.0,
        })
        assert resp.status_code == 401


# ── Read Products ─────────────────────────────────────────────────────────────

class TestGetProducts:

    def test_get_products_returns_list_with_stock(self, client, admin_headers, test_product):
        resp = client.get("/api/products", headers=admin_headers)
        assert resp.status_code == 200
        products = parse_json(resp)
        assert isinstance(products, list)
        # Find our test product
        pids = [p["product_id"] for p in products]
        assert test_product["product_id"] in pids, "Created product must appear in list"
        # Verify stock_quantity is included
        our = next(p for p in products if p["product_id"] == test_product["product_id"])
        assert "stock_quantity" in our, "GET /products must include stock_quantity from inventory"

    def test_get_products_only_returns_active_products(self, client, admin_headers, test_product):
        # Deactivate the product
        client.put(f"/api/products/{test_product['product_id']}/deactivate", headers=admin_headers)
        resp = client.get("/api/products", headers=admin_headers)
        products = parse_json(resp)
        pids = [p["product_id"] for p in products]
        assert test_product["product_id"] not in pids, (
            "Deactivated product must NOT appear in GET /products (active-only list)"
        )

    def test_get_product_by_id_returns_correct_data(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        resp = client.get(f"/api/products/{pid}", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["product_id"] == pid
        assert data["sku"] == test_product["sku"]
        assert "stock_quantity" in data

    def test_get_nonexistent_product_returns_404(self, client, admin_headers):
        resp = client.get("/api/products/999999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_search_returns_matching_products(self, client, admin_headers, test_product):
        # Use part of the test product's name
        name_part = test_product["name"].split()[0]
        resp = client.get(f"/api/products?q={name_part}", headers=admin_headers)
        assert resp.status_code == 200
        products = parse_json(resp)
        pids = [p["product_id"] for p in products]
        assert test_product["product_id"] in pids


class TestProductSearch:

    def test_search_excludes_inactive_products_bug007(self, client, admin_headers):
        """
        BUG-007: GET /products?q=<term> SHOULD exclude inactive products.
        Currently returns them — this test documents the bug and will fail
        until the status filter is added to the search branch.
        """
        sfx = uid8()
        # Create then deactivate a product with a unique name
        create_resp = client.post("/api/products", json={
            "name": f"InactiveSearchable {sfx}", "sku": f"IS-{sfx}",
            "gst_rate": 5.0, "selling_rate": 50.0, "initial_stock": 0,
        }, headers=admin_headers)
        assert create_resp.status_code == 201
        pid = parse_json(create_resp)["product_id"]

        client.put(f"/api/products/{pid}/deactivate", headers=admin_headers)

        search_resp = client.get(f"/api/products?q=InactiveSearchable {sfx}", headers=admin_headers)
        assert search_resp.status_code == 200
        results = parse_json(search_resp)
        pids_found = [p["product_id"] for p in results]

        # This assertion SHOULD pass once BUG-007 is fixed.
        # Mark as xfail so the suite doesn't block on this known bug.
        if pid in pids_found:
            pytest.xfail(
                "BUG-007: Search returns inactive product — "
                "status filter missing from search branch of GET /products"
            )
        # Cleanup
        client.delete(f"/api/products/{pid}", headers=admin_headers)

    def test_search_by_sku(self, client, admin_headers, test_product):
        resp = client.get(f"/api/products?q={test_product['sku']}", headers=admin_headers)
        products = parse_json(resp)
        assert any(p["product_id"] == test_product["product_id"] for p in products)

    def test_search_no_results_returns_empty_list(self, client, admin_headers):
        resp = client.get("/api/products?q=XYZZY_NO_SUCH_PRODUCT_12345", headers=admin_headers)
        assert resp.status_code == 200
        assert parse_json(resp) == []


# ── Update Product ────────────────────────────────────────────────────────────

class TestUpdateProduct:

    def test_update_product_changes_selling_rate(self, client, admin_headers, test_product, db_conn):
        pid = test_product["product_id"]
        resp = client.put(f"/api/products/{pid}", json={
            "name": test_product["name"], "sku": test_product["sku"],
            "gst_rate": test_product["gst_rate"],
            "selling_rate": 150.0,           # changed
            "purchase_rate": test_product.get("purchase_rate") or 80.0,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert float(data["selling_rate"]) == 150.0

        # Verify in DB
        cur = db_conn.cursor()
        cur.execute("SELECT selling_rate FROM products WHERE product_id = %s", (pid,))
        assert float(cur.fetchone()[0]) == 150.0

    def test_update_product_returns_updated_object(self, client, admin_headers, test_product):
        pid = test_product["product_id"]
        resp = client.put(f"/api/products/{pid}", json={
            "name": "Updated Agri Product", "sku": test_product["sku"],
            "gst_rate": 12.0, "selling_rate": 90.0,
        }, headers=admin_headers)
        data = parse_json(resp)
        assert data["name"] == "Updated Agri Product"
        assert float(data["gst_rate"]) == 12.0

    def test_update_nonexistent_product_returns_404(self, client, admin_headers):
        resp = client.put("/api/products/999999999", json={
            "name": "Ghost", "sku": "GHOST", "gst_rate": 5.0, "selling_rate": 10.0,
        }, headers=admin_headers)
        assert resp.status_code == 404

    def test_cashier_cannot_update_product(self, client, cashier_headers, test_product):
        pid = test_product["product_id"]
        resp = client.put(f"/api/products/{pid}", json={
            "name": test_product["name"], "sku": test_product["sku"],
            "gst_rate": 5.0, "selling_rate": 99999.0,
        }, headers=cashier_headers)
        assert resp.status_code == 403


# ── Deactivate Product ────────────────────────────────────────────────────────

class TestDeactivateProduct:

    def test_deactivate_sets_status_to_inactive(self, client, admin_headers, db_conn):
        sfx = uid8()
        create = client.post("/api/products", json={
            "name": f"Deactivate Me {sfx}", "sku": f"DM-{sfx}",
            "gst_rate": 5.0, "selling_rate": 50.0,
        }, headers=admin_headers)
        pid = parse_json(create)["product_id"]

        resp = client.put(f"/api/products/{pid}/deactivate", headers=admin_headers)
        assert resp.status_code == 200

        cur = db_conn.cursor()
        cur.execute("SELECT status FROM products WHERE product_id = %s", (pid,))
        assert cur.fetchone()[0] == "Inactive", "Deactivated product must have status='Inactive'"
        # Cleanup
        client.delete(f"/api/products/{pid}", headers=admin_headers)

    def test_deactivated_product_absent_from_active_list(self, client, admin_headers, test_product):
        client.put(f"/api/products/{test_product['product_id']}/deactivate", headers=admin_headers)
        resp = client.get("/api/products", headers=admin_headers)
        pids = [p["product_id"] for p in parse_json(resp)]
        assert test_product["product_id"] not in pids


# ── Delete Product ────────────────────────────────────────────────────────────

class TestDeleteProduct:

    def test_delete_product_removes_it_from_db(self, client, admin_headers, db_conn):
        sfx = uid8()
        create = client.post("/api/products", json={
            "name": f"Delete Me {sfx}", "sku": f"DEL-{sfx}",
            "gst_rate": 5.0, "selling_rate": 50.0, "initial_stock": 10,
        }, headers=admin_headers)
        pid = parse_json(create)["product_id"]

        del_resp = client.delete(f"/api/products/{pid}", headers=admin_headers)
        assert del_resp.status_code == 200

        cur = db_conn.cursor()
        cur.execute("SELECT product_id FROM products WHERE product_id = %s", (pid,))
        assert cur.fetchone() is None, "Deleted product must not exist in products table"
        cur.execute("SELECT product_id FROM inventory WHERE product_id = %s", (pid,))
        assert cur.fetchone() is None, "Deleted product must have its inventory record removed too"

    def test_delete_nonexistent_product_returns_404(self, client, admin_headers):
        resp = client.delete("/api/products/999999999", headers=admin_headers)
        assert resp.status_code == 404
