"""
Credit Management dashboard endpoint tests.

Covers the read-only aggregation layer added on top of the existing
customer-credit and supplier ledgers:

  GET /api/credit/overview
  GET /api/credit/customers
  GET /api/credit/suppliers
  GET /api/credit/customers/<id>/ledger
  GET /api/credit/suppliers/<id>/ledger
  GET /api/credit/export   (Excel)

Test groups:
  - Authentication / authorization
  - Overview totals (receivables, payables, net position, advances)
  - Per-customer & per-supplier breakup
  - Balance-vs-ledger reconciliation (OK vs drift)
  - FIFO aging buckets (0-30 / 31-60 / 61-90 / 90+)
  - Ledger drill-in
  - Excel export

These tests seed data directly via the DB helpers so the aging math (which
depends on transaction *dates*) can be controlled precisely.
"""

import io
import datetime

import pytest

from tests.conftest import parse_json, uid8
from tests.helpers.db_helpers import get_conn, execute

pytestmark = pytest.mark.credit


# ───────────────────────── helpers / fixtures ────────────────────────────────

def _days_ago(n: int) -> datetime.datetime:
    return datetime.datetime.now() - datetime.timedelta(days=n)


@pytest.fixture
def seeded_customer():
    """
    Create a credit customer with a known ledger and clean up afterwards.
    Yields a small API around the customer so each test can add transactions
    with explicit dates (needed for aging).
    """
    conn = get_conn()
    cur = conn.cursor()
    suffix = uid8()
    cur.execute(
        """
        INSERT INTO credit_customers (customer_code, customer_uuid, name, mobile, current_balance)
        VALUES (%s, %s, %s, %s, 0)
        RETURNING customer_id
        """,
        (f"CM{suffix}", f"uuid-{suffix}", f"Cust {suffix}", "9123450000"),
    )
    cid = cur.fetchone()[0]
    cur.close()
    conn.close()

    class _Acct:
        customer_id = cid

        @staticmethod
        def add(txn_type, amount, days_ago=0):
            execute(
                """
                INSERT INTO credit_transactions
                    (customer_id, transaction_type, amount, previous_balance, created_at)
                VALUES (%s, %s, %s, 0, %s)
                """,
                (cid, txn_type, amount, _days_ago(days_ago)),
            )

        @staticmethod
        def set_balance(bal):
            execute("UPDATE credit_customers SET current_balance=%s WHERE customer_id=%s", (bal, cid))

    yield _Acct
    execute("DELETE FROM credit_transactions WHERE customer_id=%s", (cid,))
    execute("DELETE FROM credit_customers WHERE customer_id=%s", (cid,))


@pytest.fixture
def seeded_supplier():
    """Create a supplier with a controllable ledger; clean up afterwards."""
    conn = get_conn()
    cur = conn.cursor()
    suffix = uid8()
    gst = f"29ABCDE{suffix[:4].upper()}A1Z5"
    cur.execute(
        """
        INSERT INTO suppliers (supplier_name, supplier_gst_number, mobile, current_balance)
        VALUES (%s, %s, %s, 0)
        RETURNING supplier_id
        """,
        (f"Sup {suffix}", gst, "9876540000"),
    )
    sid = cur.fetchone()[0]
    cur.close()
    conn.close()

    class _Acct:
        supplier_id = sid

        @staticmethod
        def add(txn_type, amount, days_ago=0):
            execute(
                """
                INSERT INTO supplier_transactions
                    (supplier_id, transaction_type, amount, previous_balance, new_balance, created_at)
                VALUES (%s, %s, %s, 0, 0, %s)
                """,
                (sid, txn_type, amount, _days_ago(days_ago)),
            )

        @staticmethod
        def set_balance(bal):
            execute("UPDATE suppliers SET current_balance=%s WHERE supplier_id=%s", (bal, sid))

    yield _Acct
    execute("DELETE FROM supplier_transactions WHERE supplier_id=%s", (sid,))
    execute("DELETE FROM suppliers WHERE supplier_id=%s", (sid,))


def _find(items, key, value):
    return next((i for i in items if i.get(key) == value), None)


# ───────────────────────── authentication ────────────────────────────────────

class TestCreditAuth:

    @pytest.mark.parametrize("path", [
        "/api/credit/overview",
        "/api/credit/customers",
        "/api/credit/suppliers",
        "/api/credit/export",
    ])
    def test_requires_authentication(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401

    def test_ledger_requires_authentication(self, client):
        assert client.get("/api/credit/customers/1/ledger").status_code == 401
        assert client.get("/api/credit/suppliers/1/ledger").status_code == 401

    def test_cashier_without_credit_permission_is_denied(self, client, cashier_headers):
        # Endpoints are gated by @permission_required('credit'): a cashier who has
        # not been granted the 'credit' screen permission must be denied (403),
        # preventing bulk exfiltration of the receivables/payables ledgers.
        # Admins/Managers bypass the check (covered by the admin_headers tests below).
        resp = client.get("/api/credit/overview", headers=cashier_headers)
        assert resp.status_code == 403


# ───────────────────────── overview ──────────────────────────────────────────

class TestOverview:

    def test_overview_shape(self, client, admin_headers):
        resp = client.get("/api/credit/overview", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "receivables" in data
        assert "payables" in data
        assert "net_position" in data
        assert "total_outstanding" in data["receivables"]
        assert "customer_count" in data["receivables"]
        assert "advance_total" in data["receivables"]
        assert "total_outstanding" in data["payables"]
        assert "supplier_count" in data["payables"]

    def test_receivable_balance_counts_in_overview(self, client, admin_headers, seeded_customer):
        seeded_customer.set_balance(500.00)
        data = parse_json(client.get("/api/credit/overview", headers=admin_headers))
        assert data["receivables"]["total_outstanding"] >= 500.00
        assert data["receivables"]["customer_count"] >= 1

    def test_payable_balance_counts_in_overview(self, client, admin_headers, seeded_supplier):
        seeded_supplier.set_balance(800.00)
        data = parse_json(client.get("/api/credit/overview", headers=admin_headers))
        assert data["payables"]["total_outstanding"] >= 800.00
        assert data["payables"]["supplier_count"] >= 1

    def test_net_position_is_receivables_minus_payables(self, client, admin_headers):
        data = parse_json(client.get("/api/credit/overview", headers=admin_headers))
        expected = round(data["receivables"]["total_outstanding"]
                         - data["payables"]["total_outstanding"], 2)
        assert data["net_position"] == expected

    def test_customer_advance_reported_separately_not_netted(self, client, admin_headers, seeded_customer):
        # A negative balance = customer in credit (advance). It must NOT reduce
        # the receivables outstanding total; it appears in advance_total instead.
        seeded_customer.set_balance(-300.00)
        data = parse_json(client.get("/api/credit/overview", headers=admin_headers))
        assert data["receivables"]["advance_total"] >= 300.00
        assert data["receivables"]["advance_count"] >= 1


# ───────────────────────── customer breakup ──────────────────────────────────

class TestCustomerBreakup:

    def test_breakup_shape(self, client, admin_headers):
        resp = client.get("/api/credit/customers", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "customers" in data
        assert "count" in data
        assert "total_outstanding" in data
        assert "aging" in data
        assert "reconciliation" in data

    def test_customer_with_balance_listed(self, client, admin_headers, seeded_customer):
        seeded_customer.set_balance(250.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row is not None
        assert row["current_balance"] == 250.00
        assert "aging" in row
        assert "reconciled" in row

    def test_zero_balance_customer_excluded(self, client, admin_headers, seeded_customer):
        seeded_customer.set_balance(0)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        assert _find(data["customers"], "customer_id", seeded_customer.customer_id) is None

    def test_rows_sorted_descending_by_balance(self, client, admin_headers):
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        balances = [c["current_balance"] for c in data["customers"]]
        assert balances == sorted(balances, reverse=True)

    def test_total_outstanding_excludes_advances(self, client, admin_headers):
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        positive_sum = round(sum(c["current_balance"] for c in data["customers"]
                                 if c["current_balance"] > 0), 2)
        assert data["total_outstanding"] == positive_sum


# ───────────────────────── supplier breakup ──────────────────────────────────

class TestSupplierBreakup:

    def test_breakup_shape(self, client, admin_headers):
        resp = client.get("/api/credit/suppliers", headers=admin_headers)
        assert resp.status_code == 200
        data = parse_json(resp)
        assert "suppliers" in data
        assert "aging" in data
        assert "reconciliation" in data

    def test_supplier_with_balance_listed(self, client, admin_headers, seeded_supplier):
        seeded_supplier.set_balance(999.00)
        data = parse_json(client.get("/api/credit/suppliers", headers=admin_headers))
        row = _find(data["suppliers"], "supplier_id", seeded_supplier.supplier_id)
        assert row is not None
        assert row["current_balance"] == 999.00
        assert row["supplier_name"]
        assert "supplier_gst_number" in row


# ───────────────────────── reconciliation ────────────────────────────────────

class TestReconciliation:

    def test_matching_balance_is_reconciled(self, client, admin_headers, seeded_customer):
        # Ledger: +400 credit, -150 debit => expected 250. Stored balance = 250.
        seeded_customer.add("credit", 400, days_ago=10)
        seeded_customer.add("debit", 150, days_ago=5)
        seeded_customer.set_balance(250.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["reconciled"] is True
        assert row["discrepancy"] == 0.0
        assert row["expected_balance"] == 250.00

    def test_drifted_balance_flagged(self, client, admin_headers, seeded_customer):
        # Ledger says 400 but stored balance is 999 -> drift, must be flagged.
        seeded_customer.add("credit", 400, days_ago=10)
        seeded_customer.set_balance(999.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["reconciled"] is False
        assert row["expected_balance"] == 400.00
        assert row["discrepancy"] == round(999.00 - 400.00, 2)

    def test_mismatch_counted_in_summary(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 100, days_ago=3)
        seeded_customer.set_balance(123.45)  # deliberate drift
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        assert data["reconciliation"]["mismatched_count"] >= 1
        assert data["reconciliation"]["all_reconciled"] is False

    def test_tolerance_absorbs_rounding_noise(self, client, admin_headers, seeded_customer):
        # A 0.01 difference is at the RECON_TOLERANCE boundary (<= 0.01) and must
        # still reconcile. (DECIMAL(10,2) cannot store sub-0.01 noise, so 0.01 is
        # the smallest representable discrepancy.)
        seeded_customer.add("credit", 100.00, days_ago=2)
        seeded_customer.set_balance(100.01)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["reconciled"] is True


# ───────────────────────── aging (FIFO) ──────────────────────────────────────

class TestAging:

    def test_recent_charge_in_current_bucket(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 500, days_ago=10)   # within 0-30
        seeded_customer.set_balance(500.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["aging"]["current"] == 500.00
        assert row["aging"]["d31_60"] == 0.0
        assert row["aging"]["d90_plus"] == 0.0

    def test_old_charge_in_90plus_bucket(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 700, days_ago=120)  # 90+
        seeded_customer.set_balance(700.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["aging"]["d90_plus"] == 700.00
        assert row["aging"]["current"] == 0.0

    def test_buckets_cover_all_ranges(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 100, days_ago=10)   # current
        seeded_customer.add("credit", 100, days_ago=45)   # 31-60
        seeded_customer.add("credit", 100, days_ago=75)   # 61-90
        seeded_customer.add("credit", 100, days_ago=200)  # 90+
        seeded_customer.set_balance(400.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["aging"]["current"] == 100.00
        assert row["aging"]["d31_60"] == 100.00
        assert row["aging"]["d61_90"] == 100.00
        assert row["aging"]["d90_plus"] == 100.00

    def test_fifo_payment_settles_oldest_charge_first(self, client, admin_headers, seeded_customer):
        # Old charge 300 (120d) + new charge 200 (5d); pay 300.
        # FIFO: payment knocks out the 300 old charge entirely.
        # Remaining outstanding = 200, all in the CURRENT bucket.
        seeded_customer.add("credit", 300, days_ago=120)
        seeded_customer.add("credit", 200, days_ago=5)
        seeded_customer.add("debit", 300, days_ago=1)
        seeded_customer.set_balance(200.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert row["aging"]["d90_plus"] == 0.0
        assert row["aging"]["current"] == 200.00

    def test_aging_buckets_sum_to_outstanding(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 250, days_ago=15)
        seeded_customer.add("credit", 150, days_ago=80)
        seeded_customer.set_balance(400.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        bucket_sum = round(sum(row["aging"].values()), 2)
        assert bucket_sum == 400.00

    def test_advance_balance_does_not_age(self, client, admin_headers, seeded_customer):
        # Net negative balance (advance) has nothing outstanding to age.
        seeded_customer.add("debit", 500, days_ago=10)
        seeded_customer.set_balance(-500.00)
        data = parse_json(client.get("/api/credit/customers", headers=admin_headers))
        row = _find(data["customers"], "customer_id", seeded_customer.customer_id)
        assert sum(row["aging"].values()) == 0.0


# ───────────────────────── ledger drill-in ───────────────────────────────────

class TestLedgerDrillIn:

    def test_customer_ledger_returns_transactions(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 100, days_ago=5)
        seeded_customer.add("debit", 40, days_ago=2)
        seeded_customer.set_balance(60.00)
        resp = client.get(
            f"/api/credit/customers/{seeded_customer.customer_id}/ledger",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["txn_count"] == 2
        assert data["current_balance"] == 60.00
        assert len(data["transactions"]) == 2
        types = {t["transaction_type"] for t in data["transactions"]}
        assert types == {"credit", "debit"}

    def test_customer_ledger_not_found(self, client, admin_headers):
        resp = client.get("/api/credit/customers/999999999/ledger", headers=admin_headers)
        assert resp.status_code == 404

    def test_supplier_ledger_returns_transactions(self, client, admin_headers, seeded_supplier):
        seeded_supplier.add("credit", 1000, days_ago=10)
        seeded_supplier.set_balance(1000.00)
        resp = client.get(
            f"/api/credit/suppliers/{seeded_supplier.supplier_id}/ledger",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = parse_json(resp)
        assert data["txn_count"] == 1
        assert data["current_balance"] == 1000.00

    def test_supplier_ledger_not_found(self, client, admin_headers):
        resp = client.get("/api/credit/suppliers/999999999/ledger", headers=admin_headers)
        assert resp.status_code == 404

    def test_ledger_transactions_newest_first(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 100, days_ago=30)
        seeded_customer.add("credit", 100, days_ago=1)
        seeded_customer.set_balance(200.00)
        data = parse_json(client.get(
            f"/api/credit/customers/{seeded_customer.customer_id}/ledger",
            headers=admin_headers,
        ))
        dates = [t["created_at"] for t in data["transactions"]]
        assert dates == sorted(dates, reverse=True)


# ───────────────────────── Excel export ──────────────────────────────────────

class TestExport:

    def test_export_returns_xlsx(self, client, admin_headers):
        resp = client.get("/api/credit/export", headers=admin_headers)
        assert resp.status_code == 200
        ctype = resp.headers.get("Content-Type", "")
        assert "spreadsheet" in ctype or "officedocument" in ctype

    def test_export_is_valid_workbook_with_expected_sheets(self, client, admin_headers, seeded_customer):
        seeded_customer.add("credit", 500, days_ago=15)
        seeded_customer.set_balance(500.00)
        resp = client.get("/api/credit/export", headers=admin_headers)
        assert resp.status_code == 200
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not available to inspect workbook")
        wb = openpyxl.load_workbook(io.BytesIO(resp.data))
        names = set(wb.sheetnames)
        assert "Overview" in names
        assert "By Customer" in names
        assert "By Supplier" in names

    def test_export_content_disposition_attachment(self, client, admin_headers):
        resp = client.get("/api/credit/export", headers=admin_headers)
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert ".xlsx" in cd
