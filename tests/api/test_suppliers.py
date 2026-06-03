"""
Supplier management endpoint tests.

Routes exercised:
  GET    /api/suppliers
  GET    /api/suppliers/<id>  (via data)
  POST   /api/suppliers
  PUT    /api/suppliers/<id>
  DELETE /api/suppliers/<id>
  GET    /api/suppliers/<id>/transactions
  POST   /api/suppliers/<id>/transactions
"""

import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import supplier_payload
from tests.helpers.db_helpers import get_supplier_balance, execute


pytestmark = pytest.mark.suppliers

VALID_GST = "29AABCU9603R1ZX"


# ── GET /api/suppliers ───────────────────────────────────────────────────────

class TestGetSuppliers:

    def test_returns_list_for_authenticated_user(self, client, admin_headers):
        resp = client.get("/api/suppliers", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(parse_json(resp), list)

    def test_returns_list_for_cashier(self, client, cashier_headers):
        resp = client.get("/api/suppliers", headers=cashier_headers)
        assert resp.status_code == 200

    def test_returns_401_without_token(self, client):
        resp = client.get("/api/suppliers")
        assert resp.status_code == 401

    def test_search_returns_matching_suppliers(self, client, admin_headers, test_supplier):
        name = test_supplier["supplier_name"][:8]
        resp = client.get(f"/api/suppliers?q={name}", headers=admin_headers)
        assert resp.status_code == 200
        results = parse_json(resp)
        assert any(name in s["supplier_name"] for s in results)

    def test_search_no_match_returns_empty_list(self, client, admin_headers):
        resp = client.get("/api/suppliers?q=zzz_no_such_supplier", headers=admin_headers)
        assert resp.status_code == 200
        assert parse_json(resp) == []


# ── POST /api/suppliers ──────────────────────────────────────────────────────

class TestCreateSupplier:

    def test_admin_can_create_supplier(self, client, admin_headers):
        payload = supplier_payload()
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert "supplier_id" in data
        assert data["supplier_name"] == payload["supplier_name"]
        sid = data["supplier_id"]
        execute("DELETE FROM supplier_transactions WHERE supplier_id=%s", (sid,))
        execute("DELETE FROM suppliers WHERE supplier_id=%s", (sid,))

    def test_cashier_cannot_create_supplier(self, client, cashier_headers):
        resp = client.post("/api/suppliers", json=supplier_payload(), headers=cashier_headers)
        assert resp.status_code in (401, 403)

    def test_unauthenticated_cannot_create_supplier(self, client):
        resp = client.post("/api/suppliers", json=supplier_payload())
        assert resp.status_code == 401

    def test_missing_supplier_name_returns_400(self, client, admin_headers):
        payload = supplier_payload()
        del payload["supplier_name"]
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_gst_number_returns_400(self, client, admin_headers):
        payload = supplier_payload()
        del payload["supplier_gst_number"]
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_mobile_returns_400(self, client, admin_headers):
        payload = supplier_payload()
        del payload["mobile"]
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_invalid_gst_number_returns_400(self, client, admin_headers):
        payload = supplier_payload(supplier_gst_number="INVALID_GST_123")
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400
        data = parse_json(resp)
        assert "gst" in data["message"].lower()

    def test_invalid_mobile_returns_400(self, client, admin_headers):
        payload = supplier_payload(mobile="12345")  # too short
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_duplicate_gst_number_returns_400(self, client, admin_headers, test_supplier):
        payload = supplier_payload(supplier_gst_number=test_supplier["supplier_gst_number"])
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 400
        assert "already exists" in parse_json(resp)["message"].lower()

    def test_ten_digit_mobile_is_valid(self, client, admin_headers):
        payload = supplier_payload(mobile="9876543210")
        resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        sid = parse_json(resp)["supplier_id"]
        execute("DELETE FROM suppliers WHERE supplier_id=%s", (sid,))


# ── PUT /api/suppliers/<id> ──────────────────────────────────────────────────

class TestUpdateSupplier:

    def test_admin_can_update_supplier(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        payload = {
            "supplier_name": f"Updated {uid8()}",
            "supplier_gst_number": test_supplier["supplier_gst_number"],
            "mobile": "9988776655",
        }
        resp = client.put(f"/api/suppliers/{sid}", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["supplier_name"] == payload["supplier_name"]

    def test_cashier_cannot_update_supplier(self, client, cashier_headers, test_supplier):
        resp = client.put(
            f"/api/suppliers/{test_supplier['supplier_id']}",
            json={"supplier_name": "hack"},
            headers=cashier_headers,
        )
        assert resp.status_code in (401, 403)

    def test_update_nonexistent_supplier_returns_404(self, client, admin_headers):
        resp = client.put("/api/suppliers/999999999", json={"supplier_name": "x"}, headers=admin_headers)
        assert resp.status_code == 404

    def test_update_with_invalid_gst_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.put(f"/api/suppliers/{sid}", json={"supplier_gst_number": "BAD"}, headers=admin_headers)
        assert resp.status_code == 400

    def test_no_fields_to_update_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.put(f"/api/suppliers/{sid}", json={}, headers=admin_headers)
        assert resp.status_code == 400


# ── DELETE /api/suppliers/<id> ───────────────────────────────────────────────

class TestDeleteSupplier:

    def test_admin_can_delete_supplier_without_orders(self, client, admin_headers):
        payload = supplier_payload()
        create_resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
        assert create_resp.status_code == 201
        sid = parse_json(create_resp)["supplier_id"]

        del_resp = client.delete(f"/api/suppliers/{sid}", headers=admin_headers)
        assert del_resp.status_code == 200
        assert "deleted" in parse_json(del_resp)["message"].lower()

    def test_cashier_cannot_delete_supplier(self, client, cashier_headers, test_supplier):
        resp = client.delete(f"/api/suppliers/{test_supplier['supplier_id']}", headers=cashier_headers)
        assert resp.status_code in (401, 403)

    def test_delete_nonexistent_supplier_returns_404(self, client, admin_headers):
        resp = client.delete("/api/suppliers/999999999", headers=admin_headers)
        assert resp.status_code == 404


# ── Supplier Transactions ────────────────────────────────────────────────────

class TestSupplierTransactions:

    def test_get_transactions_returns_list(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.get(f"/api/suppliers/{sid}/transactions", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(parse_json(resp), list)

    def test_get_transactions_for_nonexistent_supplier_returns_404(self, client, admin_headers):
        resp = client.get("/api/suppliers/999999999/transactions", headers=admin_headers)
        assert resp.status_code == 404

    def test_add_credit_transaction_updates_balance(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        balance_before = get_supplier_balance(sid)
        resp = client.post(
            f"/api/suppliers/{sid}/transactions",
            json={"transaction_type": "credit", "amount": 500.0, "note": "test credit"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = parse_json(resp)
        assert float(data["new_balance"]) == pytest.approx(balance_before + 500.0)

    def test_add_debit_transaction_updates_balance(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        # Seed some credit first
        client.post(f"/api/suppliers/{sid}/transactions",
                    json={"transaction_type": "credit", "amount": 1000.0},
                    headers=admin_headers)
        balance_before = get_supplier_balance(sid)
        resp = client.post(
            f"/api/suppliers/{sid}/transactions",
            json={"transaction_type": "debit", "amount": 400.0, "note": "payment"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert float(parse_json(resp)["new_balance"]) == pytest.approx(balance_before - 400.0)

    def test_missing_transaction_type_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.post(f"/api/suppliers/{sid}/transactions",
                           json={"amount": 100.0}, headers=admin_headers)
        assert resp.status_code == 400

    def test_invalid_transaction_type_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.post(f"/api/suppliers/{sid}/transactions",
                           json={"transaction_type": "borrow", "amount": 100.0},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_zero_amount_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.post(f"/api/suppliers/{sid}/transactions",
                           json={"transaction_type": "credit", "amount": 0},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_negative_amount_returns_400(self, client, admin_headers, test_supplier):
        sid = test_supplier["supplier_id"]
        resp = client.post(f"/api/suppliers/{sid}/transactions",
                           json={"transaction_type": "credit", "amount": -50},
                           headers=admin_headers)
        assert resp.status_code == 400
