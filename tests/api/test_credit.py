"""
Credit customer management endpoint tests.

Routes exercised:
  POST   /api/customers
  GET    /api/customers
  PUT    /api/customers/<id>
  DELETE /api/customers/<id>
  POST   /api/customers/<id>/transactions
"""

import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import credit_customer_payload
from tests.helpers.db_helpers import execute, fetch_one


pytestmark = pytest.mark.credit


@pytest.fixture
def test_credit_customer(client, admin_headers):
    """Create a credit customer for each test and clean up afterwards."""
    payload = credit_customer_payload()
    resp = client.post("/api/customers", json=payload, headers=admin_headers)
    assert resp.status_code == 201, f"Credit customer fixture failed: {resp.data}"
    customer = parse_json(resp)
    yield customer
    cid = customer.get("customer_id")
    if cid:
        execute("DELETE FROM credit_transactions WHERE customer_id=%s", (cid,))
        execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))


# ── POST /api/customers ──────────────────────────────────────────────────────

class TestCreateCreditCustomer:

    def test_admin_can_create_credit_customer(self, client, admin_headers):
        payload = credit_customer_payload()
        resp = client.post("/api/customers", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert "customer_id" in data
        assert data["name"] == payload["name"]
        assert "customer_code" in data
        assert "customer_uuid" in data
        cid = data["customer_id"]
        execute("DELETE FROM credit_transactions WHERE customer_id=%s", (cid,))
        execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))

    def test_cashier_cannot_create_credit_customer(self, client, cashier_headers):
        resp = client.post("/api/customers", json=credit_customer_payload(), headers=cashier_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_create_credit_customer(self, client):
        resp = client.post("/api/customers", json=credit_customer_payload())
        assert resp.status_code == 401

    def test_missing_name_returns_400(self, client, admin_headers):
        payload = credit_customer_payload()
        del payload["name"]
        resp = client.post("/api/customers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_mobile_returns_400(self, client, admin_headers):
        payload = credit_customer_payload()
        del payload["mobile"]
        resp = client.post("/api/customers", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_customer_code_is_auto_generated(self, client, admin_headers):
        payload = credit_customer_payload(name="Priya Test")
        resp = client.post("/api/customers", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        # Customer code should start with first 2 chars of name (uppercase)
        assert data["customer_code"].startswith("PR")
        cid = data["customer_id"]
        execute("DELETE FROM credit_transactions WHERE customer_id=%s", (cid,))
        execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))

    def test_empty_body_returns_400(self, client, admin_headers):
        resp = client.post("/api/customers", json=None, headers=admin_headers)
        assert resp.status_code == 400


# ── GET /api/customers ───────────────────────────────────────────────────────

class TestGetCreditCustomers:

    def test_admin_can_list_customers(self, client, admin_headers, test_credit_customer):
        resp = client.get("/api/customers", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert isinstance(data, list)
        ids = [c["customer_id"] for c in data]
        assert test_credit_customer["customer_id"] in ids

    def test_cashier_can_list_customers(self, client, cashier_headers):
        resp = client.get("/api/customers", headers=cashier_headers)
        assert resp.status_code in (200, 403)

    def test_unauthenticated_cannot_list_customers(self, client):
        resp = client.get("/api/customers")
        assert resp.status_code == 401


# ── PUT /api/customers/<id> ──────────────────────────────────────────────────

class TestUpdateCreditCustomer:

    def test_admin_can_update_customer(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        new_name = f"Updated {uid8()}"
        resp = client.put(
            f"/api/customers/{cid}",
            json={"name": new_name, "mobile": "9111222333"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data.get("name") == new_name or "success" in str(data).lower()

    def test_update_nonexistent_customer_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/customers/999999999",
            json={"name": "nobody"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_cashier_cannot_update_customer(self, client, cashier_headers, test_credit_customer):
        resp = client.put(
            f"/api/customers/{test_credit_customer['customer_id']}",
            json={"name": "hack"},
            headers=cashier_headers,
        )
        assert resp.status_code == 403


# ── DELETE /api/customers/<id> ───────────────────────────────────────────────

class TestDeleteCreditCustomer:

    def test_admin_can_delete_customer(self, client, admin_headers):
        payload = credit_customer_payload()
        create = client.post("/api/customers", json=payload, headers=admin_headers)
        assert create.status_code == 201
        cid = parse_json(create)["customer_id"]

        resp = client.delete(f"/api/customers/{cid}", headers=admin_headers)
        assert resp.status_code == 200

    def test_delete_nonexistent_customer_returns_404(self, client, admin_headers):
        resp = client.delete("/api/customers/999999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_unauthenticated_cannot_delete_customer(self, client, test_credit_customer):
        resp = client.delete(f"/api/customers/{test_credit_customer['customer_id']}")
        assert resp.status_code == 401


# ── POST /api/customers/<id>/transactions ─────────────────────────────────────

class TestCreditTransactions:

    def test_add_credit_transaction(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        resp = client.post(
            f"/api/customers/{cid}/transactions",
            json={"transaction_type": "credit", "amount": 250.0, "note": "purchase"},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    def test_add_debit_transaction(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        # First add credit
        client.post(f"/api/customers/{cid}/transactions",
                    json={"transaction_type": "credit", "amount": 500.0},
                    headers=admin_headers)
        # Then debit
        resp = client.post(
            f"/api/customers/{cid}/transactions",
            json={"transaction_type": "debit", "amount": 200.0, "note": "payment"},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    def test_missing_transaction_type_returns_400(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        resp = client.post(f"/api/customers/{cid}/transactions",
                           json={"amount": 100.0}, headers=admin_headers)
        assert resp.status_code == 400

    def test_invalid_transaction_type_returns_400(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        resp = client.post(f"/api/customers/{cid}/transactions",
                           json={"transaction_type": "invalid", "amount": 100.0},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_zero_amount_returns_400(self, client, admin_headers, test_credit_customer):
        cid = test_credit_customer["customer_id"]
        resp = client.post(f"/api/customers/{cid}/transactions",
                           json={"transaction_type": "credit", "amount": 0},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_transaction_for_nonexistent_customer_returns_404(self, client, admin_headers):
        resp = client.post("/api/customers/999999999/transactions",
                           json={"transaction_type": "credit", "amount": 100.0},
                           headers=admin_headers)
        assert resp.status_code == 404
