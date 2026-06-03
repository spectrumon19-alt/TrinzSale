"""
Database integrity tests — validates FK constraints, UNIQUE violations, CHECK
constraints, CASCADE deletes, NULL rules, rollback behaviour, and index presence.
Uses direct psycopg2 connections (no Flask app layer) for isolation.
"""

import pytest
import psycopg2
from psycopg2.extras import RealDictCursor
from tests.conftest import (
    TEST_DB_HOST, TEST_DB_NAME, TEST_DB_USER, TEST_DB_PASSWORD, TEST_DB_PORT, uid8
)

pytestmark = pytest.mark.db


# ── Raw DB fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def raw(db_conn):
    """Convenience: yields (conn, cursor) and auto-rollbacks."""
    cur = db_conn.cursor(cursor_factory=RealDictCursor)
    yield db_conn, cur
    cur.close()


# ── UNIQUE Constraints ────────────────────────────────────────────────────────

class TestUniqueConstraints:

    def test_duplicate_username_rejected(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash','Admin')",
            (f"dup_user_{sfx}",)
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash','Admin')",
                (f"dup_user_{sfx}",)
            )
            conn.commit()
        conn.rollback()

    def test_duplicate_product_sku_rejected(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0)",
            (f"Prod {sfx}", f"SKU-{sfx}")
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0)",
                (f"Prod2 {sfx}", f"SKU-{sfx}")
            )
            conn.commit()
        conn.rollback()
        # Cleanup
        cur.execute("DELETE FROM products WHERE sku=%s", (f"SKU-{sfx}",))
        conn.commit()

    def test_duplicate_supplier_gst_rejected(self, raw):
        conn, cur = raw
        sfx = uid8()
        gst = f"29ABCDE1234A1Z5"
        cur.execute(
            "INSERT INTO suppliers (supplier_name, supplier_gst_number) VALUES (%s,%s)",
            (f"Sup {sfx}", gst + sfx[:2])
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO suppliers (supplier_name, supplier_gst_number) VALUES (%s,%s)",
                (f"Sup2 {sfx}", gst + sfx[:2])
            )
            conn.commit()
        conn.rollback()
        cur.execute("DELETE FROM suppliers WHERE supplier_name LIKE %s", (f"Sup {sfx}%",))
        conn.commit()

    def test_duplicate_invoice_number_rejected(self, raw):
        conn, cur = raw
        sfx = uid8()
        # Need a valid user_id
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]
        cur.execute(
            """INSERT INTO sales_invoices (invoice_number, receipt_number, customer_name,
               user_id, total_amount, total_gst)
               VALUES (%s, %s, 'Test', %s, 100, 15)""",
            (f"D01P001_{sfx}", f"R_20260101_{sfx[:3]}", uid)
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """INSERT INTO sales_invoices (invoice_number, receipt_number, customer_name,
                   user_id, total_amount, total_gst)
                   VALUES (%s, %s, 'Test2', %s, 100, 15)""",
                (f"D01P001_{sfx}", f"R_20260101_ZZZ", uid)
            )
            conn.commit()
        conn.rollback()
        cur.execute("DELETE FROM sales_invoices WHERE invoice_number=%s", (f"D01P001_{sfx}",))
        conn.commit()

    def test_user_permissions_unique_user_page_pair(self, raw):
        conn, cur = raw
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]
        cur.execute(
            "INSERT INTO user_permissions (user_id, page_id, has_access) VALUES (%s,'test_page',TRUE)",
            (uid,)
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO user_permissions (user_id, page_id, has_access) VALUES (%s,'test_page',FALSE)",
                (uid,)
            )
            conn.commit()
        conn.rollback()
        cur.execute("DELETE FROM user_permissions WHERE user_id=%s AND page_id='test_page'", (uid,))
        conn.commit()


# ── Foreign Key Constraints ───────────────────────────────────────────────────

class TestForeignKeyConstraints:

    def test_inventory_fk_to_products(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("INSERT INTO inventory (product_id, stock_quantity) VALUES (999999, 10)")
            conn.commit()
        conn.rollback()

    def test_sales_invoice_user_fk(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO sales_invoices (invoice_number, user_id, total_amount, total_gst)
                   VALUES ('FKTEST001', 999999, 100, 15)"""
            )
            conn.commit()
        conn.rollback()

    def test_purchase_order_supplier_fk(self, raw):
        conn, cur = raw
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO purchase_orders
                   (supplier_id, purchase_order_number, user_id, total_amount)
                   VALUES (999999, 'PO-FK-TEST', %s, 100)""",
                (uid,)
            )
            conn.commit()
        conn.rollback()

    def test_purchase_order_items_fk_to_purchase_orders(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO purchase_order_items
                   (purchase_order_id, product_id, quantity, purchase_rate, total_amount)
                   VALUES (999999, 1, 10, 50.0, 500.0)"""
            )
            conn.commit()
        conn.rollback()

    def test_credit_transaction_customer_fk(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                """INSERT INTO credit_transactions
                   (customer_id, transaction_type, amount, previous_balance)
                   VALUES (999999, 'debit', 100, 0)"""
            )
            conn.commit()
        conn.rollback()


# ── CHECK Constraints ─────────────────────────────────────────────────────────

class TestCheckConstraints:

    def test_users_role_check_valid_roles(self, raw):
        conn, cur = raw
        for role in ["Admin", "Cashier", "Super Admin", "Manager"]:
            sfx = uid8()
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash',%s)",
                (f"role_test_{sfx}", role)
            )
        conn.commit()
        # Cleanup
        cur.execute("DELETE FROM users WHERE username LIKE 'role_test_%'")
        conn.commit()

    def test_users_role_check_invalid_role_rejected(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES ('bad_role_test','hash','InvalidRole')"
            )
            conn.commit()
        conn.rollback()

    def test_products_status_check_active(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate, status) VALUES (%s,%s,5.0,50.0,'Active')",
            (f"Check Active {sfx}", f"CA-{sfx}")
        )
        conn.commit()
        cur.execute("DELETE FROM products WHERE sku=%s", (f"CA-{sfx}",))
        conn.commit()

    def test_products_status_check_invalid_rejected(self, raw):
        conn, cur = raw
        sfx = uid8()
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO products (name, sku, gst_rate, selling_rate, status) VALUES (%s,%s,5.0,50.0,'Deleted')",
                (f"Bad Status {sfx}", f"BS-{sfx}")
            )
            conn.commit()
        conn.rollback()

    def test_sales_invoice_status_check(self, raw):
        conn, cur = raw
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]
        sfx = uid8()
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO sales_invoices (invoice_number, user_id, total_amount, total_gst, status)
                   VALUES (%s,%s,100,15,'Pending')""",
                (f"INV-{sfx}", uid)
            )
            conn.commit()
        conn.rollback()

    def test_login_activity_status_check(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO login_activity (username, login_status)
                   VALUES ('test_check_user', 'unknown')"""
            )
            conn.commit()
        conn.rollback()

    def test_supplier_transaction_type_check(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """INSERT INTO supplier_transactions (supplier_id, transaction_type, amount)
                   VALUES (1, 'transfer', 100)"""
            )
            conn.commit()
        conn.rollback()


# ── NOT NULL Constraints ──────────────────────────────────────────────────────

class TestNotNullConstraints:

    def test_user_username_not_null(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (NULL,'hash','Admin')")
            conn.commit()
        conn.rollback()

    def test_product_selling_rate_not_null(self, raw):
        conn, cur = raw
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute("INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES ('P',NULL,5.0,NULL)")
            conn.commit()
        conn.rollback()

    def test_sales_invoice_total_amount_not_null(self, raw):
        conn, cur = raw
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO sales_invoices (invoice_number, user_id, total_amount, total_gst) VALUES ('NN001',%s,NULL,0)",
                (uid,)
            )
            conn.commit()
        conn.rollback()


# ── CASCADE DELETE ────────────────────────────────────────────────────────────

class TestCascadeDelete:

    def test_delete_purchase_order_cascades_to_items(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute("SELECT user_id FROM users WHERE username='test_admin' LIMIT 1")
        uid = cur.fetchone()["user_id"]

        # Create a product and purchase order
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0) RETURNING product_id",
            (f"CascadeProd {sfx}", f"CP-{sfx}")
        )
        pid = cur.fetchone()["product_id"]
        cur.execute(
            "INSERT INTO purchase_orders (purchase_order_number, user_id, total_amount) VALUES (%s,%s,500.0) RETURNING purchase_order_id",
            (f"PO-CASCADE-{sfx}", uid)
        )
        poid = cur.fetchone()["purchase_order_id"]
        cur.execute(
            "INSERT INTO purchase_order_items (purchase_order_id, product_id, quantity, purchase_rate, total_amount) VALUES (%s,%s,10,50.0,500.0)",
            (poid, pid)
        )
        conn.commit()

        # Verify item exists
        cur.execute("SELECT COUNT(*) FROM purchase_order_items WHERE purchase_order_id=%s", (poid,))
        assert cur.fetchone()["count"] == 1

        # Delete PO — items must cascade
        cur.execute("DELETE FROM purchase_orders WHERE purchase_order_id=%s", (poid,))
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM purchase_order_items WHERE purchase_order_id=%s", (poid,))
        assert cur.fetchone()["count"] == 0, "CASCADE DELETE must remove purchase_order_items"

        # Cleanup
        cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))
        conn.commit()

    def test_delete_credit_customer_cascades_to_transactions(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            """INSERT INTO credit_customers (customer_code, customer_uuid, name, mobile)
               VALUES (%s,%s,%s,'9000000099') RETURNING customer_id""",
            (f"CC-{sfx}", sfx, f"Cascade Cust {sfx}")
        )
        cid = cur.fetchone()["customer_id"]
        cur.execute(
            """INSERT INTO credit_transactions (customer_id, transaction_type, amount, previous_balance)
               VALUES (%s,'credit',100,0)""",
            (cid,)
        )
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM credit_transactions WHERE customer_id=%s", (cid,))
        assert cur.fetchone()["count"] == 1

        cur.execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM credit_transactions WHERE customer_id=%s", (cid,))
        assert cur.fetchone()["count"] == 0, "CASCADE DELETE must remove credit_transactions"

    def test_delete_user_cascades_user_permissions(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash','Cashier') RETURNING user_id",
            (f"perm_cascade_{sfx}",)
        )
        uid = cur.fetchone()["user_id"]
        cur.execute(
            "INSERT INTO user_permissions (user_id, page_id, has_access) VALUES (%s,'sales',TRUE)",
            (uid,)
        )
        conn.commit()

        cur.execute("DELETE FROM users WHERE user_id=%s", (uid,))
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM user_permissions WHERE user_id=%s", (uid,))
        assert cur.fetchone()["count"] == 0, "Deleting user must CASCADE delete their permissions"


# ── Transaction Rollback ──────────────────────────────────────────────────────

class TestTransactionRollback:

    def test_rollback_undoes_insert(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash','Cashier')",
            (f"rollback_test_{sfx}",)
        )
        conn.rollback()  # explicit rollback

        cur.execute("SELECT COUNT(*) FROM users WHERE username=%s", (f"rollback_test_{sfx}",))
        assert cur.fetchone()["count"] == 0, "Rolled-back INSERT must not persist"

    def test_constraint_violation_causes_implicit_rollback(self, raw):
        conn, cur = raw
        sfx = uid8()
        # Insert valid product first
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0)",
            (f"Rollback Prod {sfx}", f"RB-{sfx}")
        )
        conn.commit()

        # Now trigger a FK violation
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("INSERT INTO inventory (product_id, stock_quantity) VALUES (999999, 10)")
            conn.commit()
        conn.rollback()

        # Original product should still exist
        cur.execute("SELECT COUNT(*) FROM products WHERE sku=%s", (f"RB-{sfx}",))
        assert cur.fetchone()["count"] == 1
        # Cleanup
        cur.execute("DELETE FROM products WHERE sku=%s", (f"RB-{sfx}",))
        conn.commit()


# ── Index Existence ───────────────────────────────────────────────────────────

class TestIndexes:

    @pytest.mark.parametrize("index_name", [
        "idx_purchase_orders_date",
        "idx_products_name",
        "idx_credit_customers_mobile",
        "idx_credit_customers_name",
        "idx_login_activity_timestamp",
        "idx_login_activity_username",
        "idx_user_permissions_user_id",
    ])
    def test_index_exists(self, db_conn, index_name):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname=%s",
            (index_name,)
        )
        assert cur.fetchone()[0] == 1, f"Index '{index_name}' must exist for query performance"


# ── NULL vs Default Handling ──────────────────────────────────────────────────

class TestNullAndDefaults:

    def test_user_created_at_defaults_to_now(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,'hash','Cashier') RETURNING created_at",
            (f"default_ts_{sfx}",)
        )
        created_at = cur.fetchone()["created_at"]
        conn.rollback()
        assert created_at is not None, "created_at must have a DEFAULT CURRENT_TIMESTAMP"

    def test_product_status_defaults_to_active(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0) RETURNING status",
            (f"Default Status {sfx}", f"DS-{sfx}")
        )
        status = cur.fetchone()["status"]
        conn.rollback()
        assert status == "Active", f"Product status should default to 'Active', got '{status}'"

    def test_inventory_stock_defaults_to_zero(self, raw):
        conn, cur = raw
        sfx = uid8()
        cur.execute(
            "INSERT INTO products (name, sku, gst_rate, selling_rate) VALUES (%s,%s,5.0,50.0) RETURNING product_id",
            (f"Inv Default {sfx}", f"ID-{sfx}")
        )
        pid = cur.fetchone()["product_id"]
        cur.execute("INSERT INTO inventory (product_id) VALUES (%s) RETURNING stock_quantity", (pid,))
        stock = cur.fetchone()["stock_quantity"]
        conn.rollback()
        assert stock == 0, f"inventory.stock_quantity must default to 0, got {stock}"
