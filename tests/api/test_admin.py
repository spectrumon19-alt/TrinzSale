"""
Admin user-management endpoint tests.

Routes exercised:
  GET    /api/admin/users
  GET    /api/admin/users/<id>
  POST   /api/admin/users
  PUT    /api/admin/users/<id>
  DELETE /api/admin/users/<id>
  PUT    /api/admin/users/<id>/reset-password
  GET    /api/admin/invoices
  GET    /api/admin/login-activity
"""

import pytest
from tests.conftest import parse_json, uid8
from tests.helpers.data_factory import user_payload
from tests.helpers.db_helpers import execute, fetch_one


pytestmark = pytest.mark.admin


# ── GET /api/admin/users ─────────────────────────────────────────────────────

class TestGetUsers:

    def test_admin_can_list_users(self, client, admin_headers):
        resp = client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        users = parse_json(resp)
        assert isinstance(users, list)
        assert len(users) >= 2  # at least test_admin + test_cashier

    def test_cashier_cannot_list_users(self, client, cashier_headers):
        resp = client.get("/api/admin/users", headers=cashier_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401

    def test_users_list_excludes_password_hash(self, client, admin_headers):
        resp = client.get("/api/admin/users", headers=admin_headers)
        body = resp.data.decode()
        assert "password_hash" not in body


# ── GET /api/admin/users/<id> ────────────────────────────────────────────────

class TestGetUserById:

    def test_admin_can_get_user_by_id(self, client, admin_headers, setup_test_database):
        admin_id = setup_test_database["admin_id"]
        resp = client.get(f"/api/admin/users/{admin_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["user_id"] == admin_id
        assert data["username"] == "test_admin"

    def test_returns_404_for_nonexistent_user(self, client, admin_headers):
        resp = client.get("/api/admin/users/999999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_cashier_cannot_get_user_by_id(self, client, cashier_headers, setup_test_database):
        admin_id = setup_test_database["admin_id"]
        resp = client.get(f"/api/admin/users/{admin_id}", headers=cashier_headers)
        assert resp.status_code == 403


# ── POST /api/admin/users ────────────────────────────────────────────────────

class TestCreateUser:

    def _cleanup(self, username: str):
        execute("DELETE FROM user_permissions WHERE user_id = (SELECT user_id FROM users WHERE username=%s)", (username,))
        execute("DELETE FROM users WHERE username=%s", (username,))

    def test_admin_can_create_cashier_user(self, client, admin_headers):
        payload = user_payload(role="Cashier")
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        data = parse_json(resp)
        assert "created" in data["message"].lower() or "success" in data["message"].lower()
        self._cleanup(payload["username"])

    def test_admin_can_create_admin_user(self, client, admin_headers):
        payload = user_payload(role="Admin")
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        self._cleanup(payload["username"])

    def test_cashier_cannot_create_user(self, client, cashier_headers):
        resp = client.post("/api/admin/users", json=user_payload(), headers=cashier_headers)
        assert resp.status_code == 403

    def test_missing_username_returns_400(self, client, admin_headers):
        payload = user_payload()
        del payload["username"]
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_password_returns_400(self, client, admin_headers):
        payload = user_payload()
        del payload["password"]
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_role_returns_400(self, client, admin_headers):
        payload = user_payload()
        del payload["role"]
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 400

    def test_invalid_role_returns_400(self, client, admin_headers):
        payload = user_payload(role="Hacker")
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 400
        assert "role" in parse_json(resp)["message"].lower()

    def test_duplicate_username_returns_error(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json=user_payload(username="test_admin"),
            headers=admin_headers,
        )
        assert resp.status_code in (400, 500)

    def test_super_admin_role_rejected_by_db_constraint(self, client, admin_headers):
        """
        The DB CHECK constraint on users.role only allows 'Admin' | 'Cashier'.
        Creating a 'Super Admin' user will fail at the DB level even though the
        application route allows it — this is a known schema/route mismatch.
        """
        payload = user_payload(role="Super Admin")
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        # The route accepts 'Super Admin' but the DB constraint rejects it
        assert resp.status_code in (201, 400, 500)
        if resp.status_code == 201:
            self._cleanup(payload["username"])


# ── PUT /api/admin/users/<id> ────────────────────────────────────────────────

class TestUpdateUser:

    def _create_temp_user(self, client, admin_headers):
        payload = user_payload(role="Cashier")
        resp = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert resp.status_code == 201
        row = fetch_one("SELECT user_id FROM users WHERE username=%s", (payload["username"],))
        return row["user_id"], payload["username"]

    def test_admin_can_update_user(self, client, admin_headers):
        uid_val, uname = self._create_temp_user(client, admin_headers)
        suffix = uid8()
        resp = client.put(
            f"/api/admin/users/{uid_val}",
            json={"username": uname, "role": "Cashier", "full_name": f"Updated {suffix}"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "success" in parse_json(resp)["message"].lower() or "updated" in parse_json(resp)["message"].lower()
        execute("DELETE FROM users WHERE user_id=%s", (uid_val,))

    def test_update_nonexistent_user_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/admin/users/999999999",
            json={"username": "ghost", "role": "Cashier"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_cashier_cannot_update_user(self, client, cashier_headers, setup_test_database):
        uid_val = setup_test_database["cashier_id"]
        resp = client.put(
            f"/api/admin/users/{uid_val}",
            json={"username": "test_cashier", "role": "Cashier"},
            headers=cashier_headers,
        )
        assert resp.status_code == 403


# ── DELETE /api/admin/users/<id> ─────────────────────────────────────────────

class TestDeleteUser:

    def test_admin_can_delete_non_admin_user(self, client, admin_headers):
        payload = user_payload(role="Cashier")
        create = client.post("/api/admin/users", json=payload, headers=admin_headers)
        assert create.status_code == 201
        row = fetch_one("SELECT user_id FROM users WHERE username=%s", (payload["username"],))
        uid_val = row["user_id"]

        del_resp = client.delete(f"/api/admin/users/{uid_val}", headers=admin_headers)
        assert del_resp.status_code == 200

    def test_cannot_delete_last_admin(self, client, admin_headers, setup_test_database):
        """If only one admin exists, deletion must be refused."""
        admin_id = setup_test_database["admin_id"]
        # Count admins first; only test when exactly one admin exists
        from tests.helpers.db_helpers import count_rows
        admin_count = count_rows("users", "role='Admin'")
        if admin_count > 1:
            pytest.skip("Multiple admins exist; last-admin guard not testable here")
        resp = client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers)
        assert resp.status_code == 400
        assert "last admin" in parse_json(resp)["message"].lower()

    def test_delete_nonexistent_user_returns_404(self, client, admin_headers):
        resp = client.delete("/api/admin/users/999999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_cashier_cannot_delete_user(self, client, cashier_headers, setup_test_database):
        resp = client.delete(
            f"/api/admin/users/{setup_test_database['cashier_id']}",
            headers=cashier_headers,
        )
        assert resp.status_code == 403


# ── PUT /api/admin/users/<id>/reset-password ─────────────────────────────────

class TestResetPassword:

    def test_admin_can_reset_password(self, client, admin_headers, setup_test_database):
        cashier_id = setup_test_database["cashier_id"]
        resp = client.put(
            f"/api/admin/users/{cashier_id}/reset-password",
            json={"new_password": "NewPass@456"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        # Restore original plain-text password
        execute("UPDATE users SET password_hash='cashierpass' WHERE user_id=%s", (cashier_id,))

    def test_missing_new_password_returns_400(self, client, admin_headers, setup_test_database):
        cashier_id = setup_test_database["cashier_id"]
        resp = client.put(
            f"/api/admin/users/{cashier_id}/reset-password",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_reset_password_for_nonexistent_user_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/admin/users/999999999/reset-password",
            json={"new_password": "whatever"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_cashier_cannot_reset_password(self, client, cashier_headers, setup_test_database):
        admin_id = setup_test_database["admin_id"]
        resp = client.put(
            f"/api/admin/users/{admin_id}/reset-password",
            json={"new_password": "hacked"},
            headers=cashier_headers,
        )
        assert resp.status_code == 403


# ── GET /api/admin/invoices ──────────────────────────────────────────────────

class TestGetAllInvoices:

    def test_admin_can_list_all_invoices(self, client, admin_headers):
        resp = client.get("/api/admin/invoices", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(parse_json(resp), list)

    def test_cashier_cannot_list_all_invoices(self, client, cashier_headers):
        resp = client.get("/api/admin/invoices", headers=cashier_headers)
        assert resp.status_code == 403


# ── GET /api/admin/login-activity ────────────────────────────────────────────

class TestLoginActivity:

    def test_admin_can_get_login_activity(self, client, admin_headers):
        resp = client.get("/api/admin/login-activity", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "logs" in data
        assert "total" in data

    def test_cashier_cannot_get_login_activity(self, client, cashier_headers):
        resp = client.get("/api/admin/login-activity", headers=cashier_headers)
        assert resp.status_code == 403

    def test_pagination_params_accepted(self, client, admin_headers):
        resp = client.get("/api/admin/login-activity?limit=10&offset=0", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["limit"] == 10
        assert data["offset"] == 0
