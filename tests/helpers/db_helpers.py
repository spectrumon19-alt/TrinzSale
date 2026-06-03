"""Direct-DB helpers for setting up and verifying test state."""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

_DB_PARAMS = dict(
    host=os.getenv("TEST_DB_HOST", "localhost"),
    dbname=os.getenv("TEST_DB_NAME", "pos_test_db"),
    user=os.getenv("TEST_DB_USER", "postgres"),
    password=os.getenv("TEST_DB_PASSWORD", "postgres"),
    port=os.getenv("TEST_DB_PORT", "5432"),
)


def get_conn(autocommit: bool = True):
    conn = psycopg2.connect(**_DB_PARAMS)
    conn.autocommit = autocommit
    return conn


def fetch_one(sql: str, params: tuple = ()):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def fetch_all(sql: str, params: tuple = ()):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def execute(sql: str, params: tuple = ()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()
    conn.close()


def get_product_stock(product_id: int) -> int:
    row = fetch_one(
        "SELECT stock_quantity FROM inventory WHERE product_id = %s", (product_id,)
    )
    return row["stock_quantity"] if row else 0


def get_invoice(invoice_id: int) -> dict | None:
    return fetch_one(
        "SELECT * FROM sales_invoices WHERE invoice_id = %s", (invoice_id,)
    )


def get_supplier_balance(supplier_id: int) -> float:
    row = fetch_one(
        "SELECT current_balance FROM suppliers WHERE supplier_id = %s", (supplier_id,)
    )
    return float(row["current_balance"]) if row else 0.0


def count_rows(table: str, where: str = "1=1", params: tuple = ()) -> int:
    row = fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)
    return int(row["n"])
