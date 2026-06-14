"""
Central test configuration, fixtures, and shared utilities for the POS system test suite.

Setup strategy:
  - Session-scoped DB schema is applied once per test run against pos_test_db.
  - Function-scoped fixtures insert and tear down isolated test records using
    unique identifiers so parallel or repeated runs never clash.
  - JWT tokens are minted directly (no round-trip through /api/login) so auth
    tests remain independent of the login endpoint.
  - Gzip middleware is handled transparently via the `parse_json` helper.
"""

import os
import sys
import gzip
import json
import uuid
import datetime

import jwt
import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Path setup – must happen before any local imports
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Override DB env-vars BEFORE importing app / db modules.
# db.py calls load_dotenv(override=True) at import time, which would clobber
# manually-set os.environ values.  We reset the pool afterwards.
# ---------------------------------------------------------------------------
TEST_DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "pos_test_db")
TEST_DB_USER = os.getenv("TEST_DB_USER", "postgres")
TEST_DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", "postgres")
TEST_DB_PORT = os.getenv("TEST_DB_PORT", "5432")
TEST_SECRET_KEY = "test-only-secret-key-not-for-production"

# Disable Flask-Limiter for the whole test session. The suite issues far more
# than the 10-logins/minute production limit, which would otherwise return 429
# and mask real assertions (this was the true cause of the auth/security 429s,
# not the account lockout). Must be set before create_app() is imported/called.
os.environ["DISABLE_RATE_LIMIT"] = "1"

import db as database  # noqa: E402 – must be after sys.path setup

# After db.py's load_dotenv ran, stomp env vars with test values.
os.environ["DB_HOST"] = TEST_DB_HOST
os.environ["DB_NAME"] = TEST_DB_NAME
os.environ["DB_USER"] = TEST_DB_USER
os.environ["DB_PASSWORD"] = TEST_DB_PASSWORD
os.environ["DB_PORT"] = TEST_DB_PORT
os.environ["SECRET_KEY"] = TEST_SECRET_KEY
database.reset_connection_pool()

from app import create_app  # noqa: E402

# The app import chain calls load_dotenv(override=True) again, which reloads the
# REAL values from .env over our test values (both SECRET_KEY and the DB_* vars).
# Re-assert all test values AFTER the app import, then rebuild the connection
# pool so the app talks to the test DB — not the developer's real database.
import auth as _auth  # noqa: E402
_auth.SECRET_KEY = TEST_SECRET_KEY
os.environ["SECRET_KEY"] = TEST_SECRET_KEY
os.environ["DB_HOST"] = TEST_DB_HOST
os.environ["DB_NAME"] = TEST_DB_NAME
os.environ["DB_USER"] = TEST_DB_USER
os.environ["DB_PASSWORD"] = TEST_DB_PASSWORD
os.environ["DB_PORT"] = TEST_DB_PORT

# db.reset_connection_pool() and the lazy pool builder both call
# load_dotenv(override=True), which would reload the developer's real .env over
# our test DB_* values every time the pool is (re)built — silently pointing the
# app at the real database. Neutralise load_dotenv inside db so the test env
# vars set above are authoritative for the whole session.
database.load_dotenv = lambda *a, **k: None
database.reset_connection_pool()

# ---------------------------------------------------------------------------
# Extra DDL that schema.sql omits but routes reference
# ---------------------------------------------------------------------------
EXTRA_DDL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email    VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mobile   VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret   VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled  BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_required BOOLEAN DEFAULT FALSE;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_by  INTEGER;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancelled_at  TIMESTAMP;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cancel_reason TEXT;

CREATE TABLE IF NOT EXISTS login_activity (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER,
    username        VARCHAR NOT NULL,
    login_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address      VARCHAR,
    user_agent      TEXT,
    browser         VARCHAR,
    os              VARCHAR,
    device_type     VARCHAR,
    location_city   VARCHAR,
    location_country VARCHAR,
    login_status    VARCHAR NOT NULL,
    failure_reason  VARCHAR
);

CREATE TABLE IF NOT EXISTS user_permissions (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    page_id    VARCHAR NOT NULL,
    has_access BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, page_id)
);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def uid8() -> str:
    """Return 8-char hex unique suffix for test record names."""
    return uuid.uuid4().hex[:8]


def make_token(user_id: int, role: str, username: str) -> str:
    """Mint a JWT token with the test secret key."""
    payload = {
        "user_id": user_id,
        "role": role,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2),
    }
    return jwt.encode(payload, TEST_SECRET_KEY, algorithm="HS256")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def parse_json(response) -> dict | list:
    """Decode a Flask test response, handling transparent gzip compression."""
    if response.headers.get("Content-Encoding") == "gzip":
        return json.loads(gzip.decompress(response.data))
    return response.get_json()


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def flask_app():
    """Create a Flask application instance wired to the test DB."""
    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = TEST_SECRET_KEY
    yield application


@pytest.fixture(scope="session")
def client(flask_app):
    """Flask test client (reused for the entire test session)."""
    return flask_app.test_client()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Apply schema.sql + supplemental DDL against the test DB once per session.
    Inserts stable seed users referenced by token fixtures.
    """
    schema_path = os.path.join(ROOT, "schema.sql")
    conn = psycopg2.connect(
        host=TEST_DB_HOST,
        dbname=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        port=TEST_DB_PORT,
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Apply base schema (idempotent – uses IF NOT EXISTS)
    with open(schema_path, encoding="utf-8") as f:
        for stmt in f.read().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except Exception:
                    pass  # Ignore errors on re-run (e.g., duplicate constraints)

    # Apply supplemental DDL
    for stmt in EXTRA_DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception:
                pass

    # Seed stable test users. password_hash must be a real pbkdf2_sha256 hash —
    # verify_password() calls pbkdf2_sha256.verify(), which rejects plain text,
    # so login-based tests need a proper hash (token fixtures mint JWTs directly).
    from passlib.hash import pbkdf2_sha256 as _pwhash
    admin_hash = _pwhash.hash("adminpass")
    cashier_hash = _pwhash.hash("cashierpass")

    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, full_name, email, mobile)
        VALUES ('test_admin', %s, 'Admin', 'Test Admin', 'admin@test.com', '9000000001')
        ON CONFLICT (username) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                role = 'Admin',
                full_name = 'Test Admin'
        RETURNING user_id
        """,
        (admin_hash,),
    )
    cur.execute("SELECT user_id FROM users WHERE username = 'test_admin'")
    admin_row = cur.fetchone()

    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, full_name, email, mobile)
        VALUES ('test_cashier', %s, 'Cashier', 'Test Cashier', 'cashier@test.com', '9000000002')
        ON CONFLICT (username) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                role = 'Cashier',
                full_name = 'Test Cashier'
        RETURNING user_id
        """,
        (cashier_hash,),
    )
    cur.execute("SELECT user_id FROM users WHERE username = 'test_cashier'")
    cashier_row = cur.fetchone()

    # Clear any stale failed-login rows so the 5-in-15min lockout doesn't carry
    # over from a previous run and turn 401 assertions into 429s.
    try:
        cur.execute("DELETE FROM login_activity WHERE username IN ('test_admin','test_cashier')")
    except Exception:
        pass

    cur.close()
    conn.close()

    # Expose user IDs for token fixtures via a simple namespace
    yield {"admin_id": admin_row[0], "cashier_id": cashier_row[0]}


# ---------------------------------------------------------------------------
# Token fixtures  (function-scoped so token data is fresh each test)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_login_lockout(setup_test_database):
    """
    Clear login_activity before each test so the custom 5-failures-in-15-min
    account lockout cannot bleed between tests. (The dominant cause of cross-test
    429s was Flask-Limiter, which is now disabled in tests via DISABLE_RATE_LIMIT;
    this remains as hygiene for the per-account lockout.)
    """
    try:
        conn = psycopg2.connect(
            host=TEST_DB_HOST, dbname=TEST_DB_NAME,
            user=TEST_DB_USER, password=TEST_DB_PASSWORD, port=TEST_DB_PORT,
        )
        conn.autocommit = True
        conn.cursor().execute("DELETE FROM login_activity")
        conn.close()
    except Exception:
        pass
    yield


@pytest.fixture
def admin_token(setup_test_database) -> str:
    return make_token(setup_test_database["admin_id"], "Admin", "test_admin")


@pytest.fixture
def cashier_token(setup_test_database) -> str:
    return make_token(setup_test_database["cashier_id"], "Cashier", "test_cashier")


@pytest.fixture
def admin_headers(admin_token) -> dict:
    return auth_headers(admin_token)


@pytest.fixture
def cashier_headers(cashier_token) -> dict:
    return auth_headers(cashier_token)


# ---------------------------------------------------------------------------
# Reusable DB connection (function-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """Raw psycopg2 connection for direct DB assertions. Rolls back after each test."""
    conn = psycopg2.connect(
        host=TEST_DB_HOST,
        dbname=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        port=TEST_DB_PORT,
    )
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Test-data fixtures – each cleans up after itself
# ---------------------------------------------------------------------------

@pytest.fixture
def test_product(client, admin_headers):
    """Create a product via API and delete it after the test."""
    suffix = uid8()
    payload = {
        "name": f"Test Product {suffix}",
        "sku": f"TST-{suffix}",
        "gst_rate": 18.0,
        "purchase_rate": 80.0,
        "selling_rate": 100.0,
        "pack_size": "1 kg",
        "initial_stock": 50,
    }
    resp = client.post("/api/products", json=payload, headers=admin_headers)
    assert resp.status_code == 201, f"Fixture setup failed: {resp.data}"
    product = parse_json(resp)
    yield product
    # Teardown – delete inventory then product directly to avoid FK constraints
    conn = psycopg2.connect(
        host=TEST_DB_HOST, dbname=TEST_DB_NAME,
        user=TEST_DB_USER, password=TEST_DB_PASSWORD, port=TEST_DB_PORT,
    )
    conn.autocommit = True
    cur = conn.cursor()
    pid = product["product_id"]
    # Delete dependent rows (deepest children first) so tests that create sales,
    # returns or purchases against this product don't trip FK constraints here.
    # Capture the invoices that reference this product before deleting their items.
    cur.execute("SELECT DISTINCT invoice_id FROM sales_invoice_items WHERE product_id = %s", (pid,))
    invoice_ids = [r[0] for r in cur.fetchall()]

    if invoice_ids:
        # sales_return_items -> sales_returns (returns reference the original invoice)
        cur.execute("""
            DELETE FROM sales_return_items WHERE return_id IN (
                SELECT return_id FROM sales_returns WHERE original_invoice_id = ANY(%s)
            )
        """, (invoice_ids,))
        cur.execute("DELETE FROM sales_returns WHERE original_invoice_id = ANY(%s)", (invoice_ids,))

    # sales_invoice_items -> sales_invoices
    cur.execute("DELETE FROM sales_invoice_items WHERE product_id = %s", (pid,))
    if invoice_ids:
        cur.execute("DELETE FROM sales_invoices WHERE invoice_id = ANY(%s)", (invoice_ids,))

    # purchases + inventory, then the product itself
    cur.execute("DELETE FROM purchase_order_items WHERE product_id = %s", (pid,))
    cur.execute("DELETE FROM inventory WHERE product_id = %s", (pid,))
    cur.execute("DELETE FROM products WHERE product_id = %s", (pid,))
    cur.close()
    conn.close()


@pytest.fixture
def test_supplier(client, admin_headers):
    """Create a supplier via API and delete it after the test."""
    suffix = uid8()
    # Valid GST format (validate_gst_number in routes/suppliers.py):
    #   2 digits + 5 upper + 4 DIGITS + 1 upper + 1[1-9A-Z] + Z + 1[0-9A-Z]
    # The 4-char block MUST be digits, so derive it from a number (not the hex
    # suffix, which may contain letters and fail the regex).
    import random as _random
    digits = f"{_random.randint(0, 9999):04d}"
    gst = f"29ABCDE{digits}A1Z5"  # 15 chars, structurally valid
    payload = {
        "supplier_name": f"Test Supplier {suffix}",
        "supplier_gst_number": gst,
        "mobile": "9876543210",
        "contact_person": "Test Contact",
        "email": f"supplier{suffix}@test.com",
        "bank_name": "Test Bank",
        "bank_account_number": "123456789",
        "ifsc_code": "SBIN0001234",
    }
    resp = client.post("/api/suppliers", json=payload, headers=admin_headers)
    assert resp.status_code == 201, f"Fixture setup failed: {resp.data}"
    supplier = parse_json(resp)
    yield supplier
    conn = psycopg2.connect(
        host=TEST_DB_HOST, dbname=TEST_DB_NAME,
        user=TEST_DB_USER, password=TEST_DB_PASSWORD, port=TEST_DB_PORT,
    )
    conn.autocommit = True
    cur = conn.cursor()
    sid = supplier["supplier_id"]
    # Remove dependent rows (children before parent) so purchase orders created
    # against this supplier don't trip FK constraints during cleanup.
    cur.execute("""
        DELETE FROM purchase_order_items WHERE purchase_order_id IN (
            SELECT purchase_order_id FROM purchase_orders WHERE supplier_id = %s
        )
    """, (sid,))
    cur.execute("DELETE FROM purchase_orders WHERE supplier_id = %s", (sid,))
    cur.execute("DELETE FROM supplier_transactions WHERE supplier_id = %s", (sid,))
    cur.execute("DELETE FROM suppliers WHERE supplier_id = %s", (sid,))
    cur.close()
    conn.close()


@pytest.fixture
def test_sale(client, cashier_headers, test_product):
    """Create a sale invoice via API. Depends on test_product fixture."""
    payload = {
        "customer_name": "Walk-In Customer",
        "mode_of_payment": "Cash",
        "items": [
            {
                "product_id": test_product["product_id"],
                "quantity": 2,
                "rate": test_product["selling_rate"],
                "gst_rate": test_product["gst_rate"],
            }
        ],
        "discount_percentage": 0,
    }
    resp = client.post("/api/sales", json=payload, headers=cashier_headers)
    assert resp.status_code == 201, f"Sale fixture setup failed: {resp.data}"
    yield parse_json(resp)
    # No explicit teardown; test_product teardown handles cascade or stock restore.
