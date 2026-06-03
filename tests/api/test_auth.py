"""
Authentication API tests — real business-logic assertions, no fake status-only checks.
Covers: login success/fail, JWT structure, /users/me, login-activity DB recording,
SQL injection safety, token expiry edge cases.
"""

import time
import pytest
from tests.conftest import parse_json, make_token, TEST_SECRET_KEY

pytestmark = pytest.mark.auth


# ── Login Success ─────────────────────────────────────────────────────────────

class TestLoginSuccess:

    def test_admin_login_returns_token_and_user_object(self, client):
        resp = client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "token" in data, "Response must contain a JWT token"
        assert "user" in data, "Response must contain a user object"
        assert data["user"]["username"] == "test_admin"
        assert data["user"]["role"] == "Admin"
        assert isinstance(data["user"]["user_id"], int) and data["user"]["user_id"] > 0

    def test_cashier_login_returns_cashier_role(self, client):
        resp = client.post("/api/login", json={"username": "test_cashier", "password": "cashierpass"})
        assert resp.status_code == 200
        assert parse_json(resp)["user"]["role"] == "Cashier"

    def test_login_token_is_valid_decodable_jwt(self, client):
        import jwt as pyjwt
        resp = client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        token = parse_json(resp)["token"]
        payload = pyjwt.decode(token, TEST_SECRET_KEY, algorithms=["HS256"])
        assert payload["username"] == "test_admin"
        assert payload["role"] == "Admin"
        assert payload.get("user_id") is not None

    def test_login_token_exp_is_in_future(self, client):
        import jwt as pyjwt
        resp = client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        payload = pyjwt.decode(parse_json(resp)["token"], TEST_SECRET_KEY, algorithms=["HS256"])
        remaining = payload["exp"] - time.time()
        assert remaining > 3600, f"Token expires in only {remaining:.0f}s — should be ≥ 1 hour"

    def test_login_response_never_exposes_password_hash(self, client):
        resp = client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        raw = resp.data.decode()
        assert "password_hash" not in raw
        assert "adminpass" not in raw, "Plain-text password must never be echoed back"


# ── Login Failure ─────────────────────────────────────────────────────────────

class TestLoginFailure:

    def test_wrong_password_returns_401(self, client):
        resp = client.post("/api/login", json={"username": "test_admin", "password": "WRONG"})
        assert resp.status_code == 401
        data = parse_json(resp)
        assert "token" not in data, "Failed login must not issue any token"
        msg = (data.get("message") or "").lower()
        assert "invalid" in msg or "credentials" in msg or "password" in msg

    def test_nonexistent_user_returns_401_not_404(self, client):
        """Must NOT reveal whether the username exists (username enumeration attack)."""
        resp = client.post("/api/login", json={"username": "ghost_xyz_9999", "password": "any"})
        assert resp.status_code == 401, "Non-existent user must return 401 not 404"
        assert "token" not in parse_json(resp)

    @pytest.mark.parametrize("body,expected_status", [
        ({"username": "", "password": "adminpass"}, 400),
        ({"username": "test_admin", "password": ""}, 400),
        ({"password": "adminpass"}, 400),
        ({"username": "test_admin"}, 400),
        ({}, 400),
        ({"username": None, "password": "adminpass"}, 400),
        ({"username": "test_admin", "password": None}, 400),
    ])
    def test_missing_or_empty_credentials_returns_400(self, client, body, expected_status):
        resp = client.post("/api/login", json=body)
        assert resp.status_code == expected_status
        assert "token" not in parse_json(resp)

    def test_case_sensitive_username(self, client):
        """Username 'TEST_ADMIN' must not match 'test_admin'."""
        resp = client.post("/api/login", json={"username": "TEST_ADMIN", "password": "adminpass"})
        assert resp.status_code == 401

    def test_case_sensitive_password(self, client):
        resp = client.post("/api/login", json={"username": "test_admin", "password": "AdminPass"})
        assert resp.status_code == 401

    def test_whitespace_only_username_rejected(self, client):
        resp = client.post("/api/login", json={"username": "   ", "password": "adminpass"})
        assert resp.status_code in (400, 401)
        assert "token" not in parse_json(resp)


# ── SQL Injection Safety ──────────────────────────────────────────────────────

class TestSQLInjection:

    @pytest.mark.parametrize("payload", [
        "' OR '1'='1",
        "' OR 1=1 --",
        "admin'--",
        "' UNION SELECT password_hash,NULL FROM users--",
        "1; DROP TABLE users--",
        "\" OR \"\"=\"",
        "') OR ('1'='1",
    ])
    def test_sql_injection_in_username_never_grants_access(self, client, payload):
        resp = client.post("/api/login", json={"username": payload, "password": "anything"})
        assert resp.status_code in (400, 401), (
            f"SQL injection '{payload}' must be rejected — got {resp.status_code}"
        )
        assert "token" not in parse_json(resp)

    @pytest.mark.parametrize("payload", [
        "' OR '1'='1", "' OR 1=1 --",
    ])
    def test_sql_injection_in_password_rejected(self, client, payload):
        resp = client.post("/api/login", json={"username": "test_admin", "password": payload})
        assert resp.status_code == 401
        assert "token" not in parse_json(resp)

    def test_users_table_still_intact_after_injection_attempt(self, client, db_conn):
        """Verify the users table was not dropped/modified by injection attempts."""
        client.post("/api/login", json={"username": "'; DROP TABLE users;--", "password": "x"})
        cur = db_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE username IN ('test_admin','test_cashier')")
        count = cur.fetchone()[0]
        assert count == 2, "users table must not be affected by injection attempt"


# ── Login Activity DB Recording ───────────────────────────────────────────────

class TestLoginActivity:

    def test_successful_login_creates_success_activity_row(self, client, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM login_activity WHERE username=%s AND login_status='success'",
            ("test_admin",)
        )
        before = cur.fetchone()[0]

        client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        db_conn.commit()

        cur.execute(
            "SELECT COUNT(*) FROM login_activity WHERE username=%s AND login_status='success'",
            ("test_admin",)
        )
        after = cur.fetchone()[0]
        assert after > before, "Successful login must write a row to login_activity"

    def test_failed_login_creates_failed_activity_row_with_reason(self, client, db_conn):
        client.post("/api/login", json={"username": "test_admin", "password": "badpassword_xyz"})
        db_conn.commit()
        cur = db_conn.cursor()
        cur.execute("""
            SELECT failure_reason FROM login_activity
            WHERE username='test_admin' AND login_status='failed'
            ORDER BY login_timestamp DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "Failed login must create a login_activity record"
        assert row[0], "failure_reason column must be populated"

    def test_login_activity_stores_correct_username(self, client, db_conn):
        client.post("/api/login", json={"username": "test_cashier", "password": "cashierpass"})
        db_conn.commit()
        cur = db_conn.cursor()
        cur.execute("""
            SELECT username, login_status FROM login_activity
            WHERE username='test_cashier' ORDER BY login_timestamp DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row[0] == "test_cashier"
        assert row[1] == "success"


# ── GET /api/users/me ─────────────────────────────────────────────────────────

class TestGetCurrentUser:

    def test_me_returns_correct_admin_identity(self, client, admin_headers):
        resp = client.get("/api/users/me", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["username"] == "test_admin"
        assert data["role"] == "Admin"
        assert isinstance(data["user_id"], int)

    def test_me_returns_correct_cashier_identity(self, client, cashier_headers):
        resp = client.get("/api/users/me", headers=cashier_headers)
        assert resp.status_code == 200
        assert parse_json(resp)["role"] == "Cashier"

    def test_me_without_token_returns_401(self, client):
        assert client.get("/api/users/me").status_code == 401

    def test_me_with_malformed_bearer_returns_401(self, client):
        resp = client.get("/api/users/me", headers={"Authorization": "Token abc"})
        assert resp.status_code == 401

    def test_me_with_expired_token_returns_401(self, client):
        import jwt as pyjwt, datetime
        expired = pyjwt.encode(
            {"user_id": 1, "role": "Admin", "username": "test_admin",
             "exp": datetime.datetime.utcnow() - datetime.timedelta(seconds=10)},
            TEST_SECRET_KEY, algorithm="HS256"
        )
        resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401

    def test_me_does_not_expose_password_hash(self, client, admin_headers):
        resp = client.get("/api/users/me", headers=admin_headers)
        assert "password" not in resp.data.decode().lower()

    def test_me_token_with_tampered_role_rejected(self, client, setup_test_database):
        """Tampered JWT with elevated role must not be accepted."""
        import jwt as pyjwt
        tampered = pyjwt.encode(
            {"user_id": setup_test_database["cashier_id"], "role": "Admin",
             "username": "test_cashier", "exp": time.time() + 3600},
            "wrong-secret-key", algorithm="HS256"
        )
        resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401, "Token signed with wrong secret must be rejected"
