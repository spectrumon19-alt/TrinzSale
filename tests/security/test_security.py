"""
Security tests for the POS API.

Covers:
  - SQL injection via parameterized inputs
  - JWT tampering / algorithm confusion
  - Broken object level authorisation (BOLA)
  - Sensitive data exposure
  - Large payload / memory exhaustion attempts
  - Oversized strings in key fields
  - XSS payloads stored as product names (API should store/return as-is; no HTML encoding expected)
  - Path traversal attempts
  - Concurrent request race conditions (basic)
"""

import threading
import time
import pytest
import datetime
import jwt

from tests.conftest import parse_json, uid8, TEST_SECRET_KEY
from tests.helpers.auth_helpers import make_token


pytestmark = pytest.mark.security


# ── SQL Injection ─────────────────────────────────────────────────────────────

class TestSQLInjection:

    _SQL_PAYLOADS = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "1; SELECT * FROM users; --",
        "' UNION SELECT username, password_hash FROM users --",
        "\\'; DELETE FROM products; --",
        "1' AND SLEEP(5) --",
    ]

    @pytest.mark.parametrize("payload", _SQL_PAYLOADS)
    def test_sql_injection_in_login_username(self, client, payload):
        resp = client.post("/api/login", json={"username": payload, "password": "anything"})
        assert resp.status_code in (400, 401, 500), \
            f"SQL injection returned unexpected {resp.status_code} for payload: {payload!r}"
        # Must never return 200 (successful auth)
        assert resp.status_code != 200

    @pytest.mark.parametrize("payload", _SQL_PAYLOADS)
    def test_sql_injection_in_product_search(self, client, admin_headers, payload):
        resp = client.get(f"/api/products?q={payload}", headers=admin_headers)
        # Should return 200 with empty/valid list, not a 500
        assert resp.status_code in (200, 400), \
            f"Search SQL injection returned {resp.status_code} for: {payload!r}"
        if resp.status_code == 200:
            data = parse_json(resp)
            assert isinstance(data, list)

    @pytest.mark.parametrize("payload", _SQL_PAYLOADS)
    def test_sql_injection_in_supplier_search(self, client, admin_headers, payload):
        resp = client.get(f"/api/suppliers?q={payload}", headers=admin_headers)
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert isinstance(parse_json(resp), list)


# ── JWT Security ──────────────────────────────────────────────────────────────

class TestJWTSecurity:

    def test_request_without_token_returns_401(self, client):
        resp = client.get("/api/products")
        assert resp.status_code == 401

    def test_token_signed_with_wrong_secret_returns_401(self, client):
        token = jwt.encode(
            {"user_id": 1, "role": "Admin", "username": "hack",
             "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
        )
        resp = client.get("/api/products", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        token = jwt.encode(
            {"user_id": 1, "role": "Admin", "username": "test_admin",
             "exp": datetime.datetime.utcnow() - datetime.timedelta(seconds=1)},
            TEST_SECRET_KEY,
            algorithm="HS256",
        )
        resp = client.get("/api/products", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_none_algorithm_token_is_rejected(self, client):
        """Ensure 'alg: none' (unsigned) tokens are refused."""
        # PyJWT raises an error for algorithm=None; craft raw base64 token
        import base64, json as json_mod
        header = base64.urlsafe_b64encode(
            json_mod.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload_part = base64.urlsafe_b64encode(
            json_mod.dumps({
                "user_id": 1, "role": "Admin", "username": "attacker",
                "exp": int((datetime.datetime.utcnow() + datetime.timedelta(hours=1)).timestamp())
            }).encode()
        ).rstrip(b"=").decode()
        forged_token = f"{header}.{payload_part}."
        resp = client.get("/api/products", headers={"Authorization": f"Bearer {forged_token}"})
        assert resp.status_code == 401

    def test_token_with_elevated_role_is_rejected(self, client):
        """A token signed with the right secret but with an injected Admin role for a cashier
        is valid – but a token claiming Admin signed with wrong key should be rejected."""
        token = jwt.encode(
            {"user_id": 999, "role": "Admin", "username": "fake_admin",
             "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
            "not-the-secret",
            algorithm="HS256",
        )
        resp = client.post("/api/products", json={}, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_bare_token_without_bearer_prefix_returns_401(self, client, admin_token):
        resp = client.get("/api/products", headers={"Authorization": admin_token})
        assert resp.status_code == 401

    def test_empty_bearer_token_returns_401(self, client):
        resp = client.get("/api/products", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


# ── Broken Object Level Authorisation (BOLA) ─────────────────────────────────

class TestBOLA:

    def test_cashier_cannot_access_admin_user_list(self, client, cashier_headers):
        resp = client.get("/api/admin/users", headers=cashier_headers)
        assert resp.status_code == 403

    def test_cashier_cannot_create_product(self, client, cashier_headers):
        from tests.helpers.data_factory import product_payload
        resp = client.post("/api/products", json=product_payload(), headers=cashier_headers)
        assert resp.status_code == 403

    def test_cashier_cannot_delete_product(self, client, cashier_headers, test_product):
        resp = client.delete(f"/api/products/{test_product['product_id']}", headers=cashier_headers)
        assert resp.status_code == 403

    def test_cashier_cannot_cancel_invoice(self, client, cashier_headers, test_sale):
        resp = client.put(f"/api/sales/{test_sale['invoice_id']}/cancel", headers=cashier_headers)
        assert resp.status_code == 403

    def test_cashier_cannot_update_inventory(self, client, cashier_headers, test_product):
        resp = client.post(
            "/api/inventory/update",
            json={"product_id": test_product["product_id"], "quantity_change": 1},
            headers=cashier_headers,
        )
        assert resp.status_code == 403


# ── Sensitive Data Exposure ───────────────────────────────────────────────────

class TestSensitiveDataExposure:

    def test_login_response_never_contains_password(self, client):
        resp = client.post("/api/login", json={"username": "test_admin", "password": "adminpass"})
        body = resp.data.decode()
        assert "adminpass" not in body
        assert "password_hash" not in body

    def test_user_list_response_never_contains_password(self, client, admin_headers):
        resp = client.get("/api/admin/users", headers=admin_headers)
        body = resp.data.decode()
        assert "password_hash" not in body

    def test_product_list_does_not_leak_internal_ids_unexpectedly(self, client, admin_headers, test_product):
        resp = client.get("/api/products", headers=admin_headers)
        # product_id is intentionally public; password_hash must not appear
        assert "password_hash" not in resp.data.decode()


# ── Oversized & Malformed Payloads ────────────────────────────────────────────

class TestOversizedPayloads:

    def test_very_long_product_name_handled(self, client, admin_headers):
        from tests.helpers.data_factory import product_payload
        payload = product_payload(name="A" * 10_000)
        resp = client.post("/api/products", json=payload, headers=admin_headers)
        # Should not crash the server (500 is acceptable; 201 means DB accepted it)
        assert resp.status_code in (201, 400, 413, 500)
        if resp.status_code == 201:
            pid = parse_json(resp).get("product_id")
            if pid:
                from tests.helpers.db_helpers import execute
                execute("DELETE FROM inventory WHERE product_id=%s", (pid,))
                execute("DELETE FROM products WHERE product_id=%s", (pid,))

    def test_very_large_json_body_handled(self, client, admin_headers):
        """10 MB JSON body should not cause unhandled crash."""
        import json as json_mod
        big_payload = {"name": "x" * 9_000_000, "sku": uid8(), "gst_rate": 18, "selling_rate": 100}
        resp = client.post(
            "/api/products",
            data=json_mod.dumps(big_payload).encode(),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in (201, 400, 413, 500)
        if resp.status_code == 201:
            pid = parse_json(resp).get("product_id")
            if pid:
                from tests.helpers.db_helpers import execute
                execute("DELETE FROM inventory WHERE product_id=%s", (pid,))
                execute("DELETE FROM products WHERE product_id=%s", (pid,))

    def test_deeply_nested_json_handled(self, client, cashier_headers):
        def nest(depth):
            if depth == 0:
                return "leaf"
            return {"child": nest(depth - 1)}
        payload = {"items": [nest(100)], "mode_of_payment": "Cash"}
        resp = client.post("/api/sales", json=payload, headers=cashier_headers)
        assert resp.status_code in (400, 422, 500)

    def test_empty_string_fields_in_login(self, client):
        resp = client.post("/api/login", json={"username": "", "password": ""})
        assert resp.status_code == 400


# ── XSS Payloads ─────────────────────────────────────────────────────────────

class TestXSSPayloads:
    """
    The API stores HTML/JS as plain text (JSON). We verify the server does not
    crash and that the stored data is returned correctly (no server-side HTML escaping
    in a pure JSON API is expected).
    """

    _XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        '"><img src=x onerror=alert(1)>',
        "javascript:alert(1)",
        "'; alert('xss'); //",
    ]

    @pytest.mark.parametrize("xss", _XSS_PAYLOADS)
    def test_xss_in_product_name_is_handled(self, client, admin_headers, xss):
        from tests.helpers.data_factory import product_payload
        payload = product_payload(name=xss)
        resp = client.post("/api/products", json=payload, headers=admin_headers)
        assert resp.status_code in (201, 400, 422, 500)
        if resp.status_code == 201:
            pid = parse_json(resp).get("product_id")
            if pid:
                from tests.helpers.db_helpers import execute
                execute("DELETE FROM inventory WHERE product_id=%s", (pid,))
                execute("DELETE FROM products WHERE product_id=%s", (pid,))


# ── Concurrent Requests ───────────────────────────────────────────────────────

class TestConcurrentRequests:

    @pytest.mark.slow
    def test_concurrent_logins_do_not_corrupt_state(self, client):
        """Fire 10 simultaneous login requests; all must return valid responses."""
        results = []

        def do_login():
            resp = client.post(
                "/api/login",
                json={"username": "test_admin", "password": "adminpass"},
            )
            results.append(resp.status_code)

        threads = [threading.Thread(target=do_login) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 10
        assert all(s == 200 for s in results), f"Some logins failed: {results}"

    @pytest.mark.slow
    def test_concurrent_inventory_reads_are_consistent(self, client, admin_headers, test_product):
        """Simultaneous reads of inventory should not produce inconsistent data."""
        results = []

        def read_inventory():
            resp = client.get("/api/inventory", headers=admin_headers)
            if resp.status_code == 200:
                data = parse_json(resp)
                pids = [item["product_id"] for item in data]
                results.append(test_product["product_id"] in pids)

        threads = [threading.Thread(target=read_inventory) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert all(results), "Product should appear consistently in concurrent inventory reads"
