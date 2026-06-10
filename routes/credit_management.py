"""
Credit Management — unified receivables (customers) and payables (suppliers).

Read-only aggregation layer built on the existing ledgers:
  • credit_customers / credit_transactions   → receivables (money owed TO us)
  • suppliers / supplier_transactions          → payables  (money WE owe)

No new tables and no writes — every figure is derived from data the
customer-credit and supplier modules already maintain.

Ledger sign convention (identical on both sides):
    transaction_type 'credit' → balance increases
    transaction_type 'debit'  → balance decreases
    => expected_balance = SUM(credit) - SUM(debit)

`current_balance` is a stored running total; the reconciliation check
re-derives the expected balance from the ledger and flags any account
where the two disagree (drift from a bug, manual edit or failed txn).
"""

import io
import logging
from datetime import date, datetime

from flask import Blueprint, jsonify, request, send_file
from psycopg2.extras import RealDictCursor

from auth import token_required
from db import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)
credit_management_bp = Blueprint('credit_management', __name__)

# Balances within this tolerance are treated as reconciled (float/rounding noise)
RECON_TOLERANCE = 0.01

# Aging bucket boundaries (days). A balance is bucketed by the age of the
# oldest unpaid charge once payments are applied oldest-first (FIFO).
AGING_BUCKETS = ['current', 'd31_60', 'd61_90', 'd90_plus']
AGING_LABELS = {
    'current':  '0–30 days',
    'd31_60':   '31–60 days',
    'd61_90':   '61–90 days',
    'd90_plus': '90+ days',
}


def _f(v):
    """Safe float."""
    return float(v) if v is not None else 0.0


def _age_days(when):
    """Whole days between `when` (date/datetime) and today."""
    if when is None:
        return 0
    d = when.date() if isinstance(when, datetime) else when
    return (date.today() - d).days


def _bucket_for(age):
    if age <= 30:
        return 'current'
    if age <= 60:
        return 'd31_60'
    if age <= 90:
        return 'd61_90'
    return 'd90_plus'


def _age_ledger(rows):
    """
    FIFO aging for one account.

    `rows` are that account's ledger entries (each: transaction_type, amount,
    created_at), ANY order. Payments (debits) settle the oldest outstanding
    charges (credits) first; the unpaid remainder of each charge is then placed
    in an aging bucket by the charge's age. Only positive net balances age
    (a net advance/credit balance has nothing outstanding to age).

    Returns {bucket: amount, ...} that sums to max(net_balance, 0).
    """
    charges = []          # list of [age_days, remaining_amount], oldest first
    payment_pool = 0.0
    for r in rows:
        amt = _f(r['amount'])
        if r['transaction_type'] == 'credit':
            charges.append([_age_days(r['created_at']), amt])
        else:
            payment_pool += amt

    # Oldest charges first so payments knock them down in FIFO order
    charges.sort(key=lambda c: -c[0])  # larger age = older = first
    for c in charges:
        if payment_pool <= 0:
            break
        take = min(payment_pool, c[1])
        c[1] -= take
        payment_pool -= take

    buckets = {b: 0.0 for b in AGING_BUCKETS}
    for age, remaining in charges:
        if remaining > 0.005:
            buckets[_bucket_for(age)] += remaining
    return {b: round(v, 2) for b, v in buckets.items()}


# ── GET /api/credit/overview ──────────────────────────────────────────────────
@credit_management_bp.route('/credit/overview', methods=['GET'])
@token_required
def credit_overview(payload):
    """Headline totals for both sides plus the net position."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Receivables — customers owe us (only positive balances count as outstanding)
        cur.execute("""
            SELECT
                COALESCE(SUM(current_balance), 0)                     AS total_outstanding,
                COUNT(*) FILTER (WHERE current_balance > 0)           AS customer_count,
                COALESCE(SUM(CASE WHEN current_balance < 0
                                  THEN current_balance ELSE 0 END), 0) AS advance_credit
            FROM credit_customers
            WHERE current_balance > 0
        """)
        recv = cur.fetchone()

        # Customers in credit (we owe them / advance) — separate, informational
        cur.execute("""
            SELECT COALESCE(SUM(current_balance), 0) AS advance_total,
                   COUNT(*)                          AS advance_count
            FROM credit_customers
            WHERE current_balance < 0
        """)
        recv_adv = cur.fetchone()

        # Payables — we owe suppliers
        cur.execute("""
            SELECT
                COALESCE(SUM(current_balance), 0)           AS total_outstanding,
                COUNT(*) FILTER (WHERE current_balance > 0) AS supplier_count
            FROM suppliers
            WHERE current_balance > 0
        """)
        pay = cur.fetchone()

        receivables_total = _f(recv['total_outstanding'])
        payables_total    = _f(pay['total_outstanding'])

        return jsonify({
            'receivables': {
                'total_outstanding': round(receivables_total, 2),
                'customer_count':    int(recv['customer_count']),
                'advance_total':     round(abs(_f(recv_adv['advance_total'])), 2),
                'advance_count':     int(recv_adv['advance_count']),
            },
            'payables': {
                'total_outstanding': round(payables_total, 2),
                'supplier_count':    int(pay['supplier_count']),
            },
            # Positive = net owed TO us; Negative = net WE owe
            'net_position': round(receivables_total - payables_total, 2),
        }), 200
    except Exception as e:
        logger.exception("Credit overview error")
        return jsonify({'message': 'Failed to load credit overview', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── Shared account-list builder (customers & suppliers) ───────────────────────
# Per-side configuration so one builder serves both ledgers.
_SIDE = {
    'customer': {
        'master':     'credit_customers',
        'ledger':     'credit_transactions',
        'id_col':     'customer_id',
        'name_col':   'name',
        'extra_cols': ['customer_code'],
    },
    'supplier': {
        'master':     'suppliers',
        'ledger':     'supplier_transactions',
        'id_col':     'supplier_id',
        'name_col':   'supplier_name',
        'extra_cols': ['supplier_gst_number'],
    },
}


def _build_account_list(cur, side):
    """
    Return (accounts, summary) for one side, with reconciliation + FIFO aging.
    Two queries total: master rows, then all ledger rows grouped in Python —
    so aging stays accurate without N+1 round-trips.
    """
    cfg = _SIDE[side]
    id_col   = cfg['id_col']
    name_col = cfg['name_col']
    extra    = cfg['extra_cols']
    extra_sql = ''.join(f'm.{c}, ' for c in extra)

    # Master rows with a non-zero balance
    cur.execute(f"""
        SELECT m.{id_col} AS account_id, m.{name_col} AS name, m.mobile,
               {extra_sql} m.current_balance
        FROM {cfg['master']} m
        WHERE m.current_balance <> 0
        ORDER BY m.current_balance DESC
    """)
    master_rows = cur.fetchall()
    if not master_rows:
        return [], _empty_summary()

    ids = [r['account_id'] for r in master_rows]

    # All ledger rows for those accounts, in one shot
    cur.execute(f"""
        SELECT {id_col} AS account_id, transaction_type, amount, created_at
        FROM {cfg['ledger']}
        WHERE {id_col} = ANY(%s)
    """, (ids,))
    ledger_by_acct = {}
    for lr in cur.fetchall():
        ledger_by_acct.setdefault(lr['account_id'], []).append(lr)

    accounts = []
    summary = _empty_summary()
    for r in master_rows:
        acct_id = r['account_id']
        balance = _f(r['current_balance'])
        led = ledger_by_acct.get(acct_id, [])

        expected = sum(_f(x['amount']) if x['transaction_type'] == 'credit'
                       else -_f(x['amount']) for x in led)
        reconciled = abs(balance - expected) <= RECON_TOLERANCE
        last_activity = max((x['created_at'] for x in led), default=None)
        aging = _age_ledger(led)

        if not reconciled:
            summary['mismatched_count'] += 1
        if balance > 0:
            summary['total_outstanding'] += balance
            for b in AGING_BUCKETS:
                summary['aging'][b] += aging[b]

        item = {
            'account_id':       acct_id,
            f'{side}_id':       acct_id,                 # customer_id / supplier_id
            'name':             r['name'],
            'mobile':           r['mobile'],
            'current_balance':  round(balance, 2),
            'expected_balance': round(expected, 2),
            'reconciled':       reconciled,
            'discrepancy':      round(balance - expected, 2),
            'txn_count':        len(led),
            'last_activity':    last_activity.isoformat() if last_activity else None,
            'aging':            aging,
        }
        for c in extra:
            item[c] = r[c]
        accounts.append(item)

    summary['total_outstanding'] = round(summary['total_outstanding'], 2)
    summary['aging'] = {b: round(v, 2) for b, v in summary['aging'].items()}
    summary['count'] = len(accounts)
    summary['all_reconciled'] = summary['mismatched_count'] == 0
    return accounts, summary


def _empty_summary():
    return {
        'count': 0,
        'total_outstanding': 0.0,
        'mismatched_count': 0,
        'all_reconciled': True,
        'aging': {b: 0.0 for b in AGING_BUCKETS},
    }


# ── GET /api/credit/customers ─────────────────────────────────────────────────
@credit_management_bp.route('/credit/customers', methods=['GET'])
@token_required
def credit_by_customer(payload):
    """Receivables per customer, with reconciliation + FIFO aging buckets."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        accounts, summary = _build_account_list(cur, 'customer')
        # Keep customer_code/customer_id keys the existing UI already reads
        for a in accounts:
            a['customer_id'] = a['account_id']
        return jsonify({
            'customers':         accounts,
            'count':             summary['count'],
            'total_outstanding': summary['total_outstanding'],
            'aging':             summary['aging'],
            'aging_labels':      AGING_LABELS,
            'reconciliation': {
                'mismatched_count': summary['mismatched_count'],
                'all_reconciled':   summary['all_reconciled'],
            },
        }), 200
    except Exception as e:
        logger.exception("Credit by-customer error")
        return jsonify({'message': 'Failed to load customer credit', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/credit/suppliers ─────────────────────────────────────────────────
@credit_management_bp.route('/credit/suppliers', methods=['GET'])
@token_required
def credit_by_supplier(payload):
    """Payables per supplier, with reconciliation + FIFO aging buckets."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        accounts, summary = _build_account_list(cur, 'supplier')
        for a in accounts:
            a['supplier_id']   = a['account_id']
            a['supplier_name'] = a['name']
        return jsonify({
            'suppliers':         accounts,
            'count':             summary['count'],
            'total_outstanding': summary['total_outstanding'],
            'aging':             summary['aging'],
            'aging_labels':      AGING_LABELS,
            'reconciliation': {
                'mismatched_count': summary['mismatched_count'],
                'all_reconciled':   summary['all_reconciled'],
            },
        }), 200
    except Exception as e:
        logger.exception("Credit by-supplier error")
        return jsonify({'message': 'Failed to load supplier credit', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/credit/customers/<id>/ledger ─────────────────────────────────────
@credit_management_bp.route('/credit/customers/<int:customer_id>/ledger', methods=['GET'])
@token_required
def customer_ledger(payload, customer_id):
    """Full transaction ledger for one customer (drill-in)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT customer_id, customer_code, name, mobile, current_balance
            FROM credit_customers WHERE customer_id = %s
        """, (customer_id,))
        acct = cur.fetchone()
        if not acct:
            return jsonify({'message': 'Customer not found'}), 404

        cur.execute("""
            SELECT transaction_id, transaction_type, amount, invoice_no, note,
                   previous_balance, created_at
            FROM credit_transactions
            WHERE customer_id = %s
            ORDER BY created_at DESC, transaction_id DESC
        """, (customer_id,))
        txns = cur.fetchall()
        return jsonify(_ledger_payload(acct, acct['name'], txns)), 200
    except Exception as e:
        logger.exception("Customer ledger error")
        return jsonify({'message': 'Failed to load ledger', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/credit/suppliers/<id>/ledger ─────────────────────────────────────
@credit_management_bp.route('/credit/suppliers/<int:supplier_id>/ledger', methods=['GET'])
@token_required
def supplier_ledger(payload, supplier_id):
    """Full transaction ledger for one supplier (drill-in)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT supplier_id, supplier_name, supplier_gst_number, mobile, current_balance
            FROM suppliers WHERE supplier_id = %s
        """, (supplier_id,))
        acct = cur.fetchone()
        if not acct:
            return jsonify({'message': 'Supplier not found'}), 404

        cur.execute("""
            SELECT transaction_id, transaction_type, amount, purchase_order_number,
                   note, previous_balance, new_balance, created_at
            FROM supplier_transactions
            WHERE supplier_id = %s
            ORDER BY created_at DESC, transaction_id DESC
        """, (supplier_id,))
        txns = cur.fetchall()
        return jsonify(_ledger_payload(acct, acct['supplier_name'], txns)), 200
    except Exception as e:
        logger.exception("Supplier ledger error")
        return jsonify({'message': 'Failed to load ledger', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


def _ledger_payload(acct, name, txns):
    out = []
    for t in txns:
        out.append({
            'transaction_id':   t['transaction_id'],
            'transaction_type': t['transaction_type'],
            'amount':           _f(t['amount']),
            'reference':        t.get('invoice_no') or t.get('purchase_order_number') or '',
            'note':             t.get('note') or '',
            'previous_balance': _f(t.get('previous_balance')),
            'created_at':       t['created_at'].isoformat() if t['created_at'] else None,
        })
    return {
        'name':            name,
        'mobile':          acct.get('mobile'),
        'current_balance': round(_f(acct['current_balance']), 2),
        'transactions':    out,
        'txn_count':       len(out),
    }


# ── GET /api/credit/export ────────────────────────────────────────────────────
@credit_management_bp.route('/credit/export', methods=['GET'])
@token_required
def export_credit(payload):
    """Excel workbook: overview, customer breakup, supplier breakup (with aging)."""
    try:
        import xlsxwriter
    except ImportError:
        return jsonify({'error': 'xlsxwriter not installed. Run: pip install xlsxwriter'}), 500

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        customers, c_sum = _build_account_list(cur, 'customer')
        suppliers, s_sum = _build_account_list(cur, 'supplier')
    except Exception as e:
        cur.close(); release_db_connection(conn)
        logger.exception("Credit export build error")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            cur.close(); release_db_connection(conn)
        except Exception:
            pass

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})

    title = wb.add_format({'bold': True, 'font_size': 13, 'font_color': '#4f46e5'})
    hdr   = wb.add_format({'bold': True, 'bg_color': '#4f46e5', 'font_color': '#fff',
                           'border': 1, 'font_size': 9, 'align': 'center', 'valign': 'vcenter'})
    cell  = wb.add_format({'border': 1, 'font_size': 9, 'valign': 'vcenter'})
    money = wb.add_format({'border': 1, 'font_size': 9, 'num_format': '₹#,##0.00', 'align': 'right'})
    money_b = wb.add_format({'border': 1, 'font_size': 9, 'num_format': '₹#,##0.00',
                             'align': 'right', 'bold': True, 'bg_color': '#eef2ff'})
    sub   = wb.add_format({'bold': True, 'font_size': 10, 'bg_color': '#eef2ff',
                           'border': 1, 'font_color': '#3730a3'})

    # ── Sheet 1: Overview ────────────────────────────────────────────────────
    ws = wb.add_worksheet('Overview')
    ws.set_column('A:A', 32); ws.set_column('B:B', 18)
    today = date.today().strftime('%d-%b-%Y')
    ws.write('A1', f'Credit Overview — as on {today}', title)
    ws.write('A2', 'TrintzPOS — auto-generated')
    r = 4
    rows = [
        ('Receivables — outstanding (owed to you)', c_sum['total_outstanding']),
        ('Receivables — customers outstanding',     c_sum['count']),
        ('Payables — outstanding (you owe)',        s_sum['total_outstanding']),
        ('Payables — suppliers outstanding',        s_sum['count']),
        ('Net position (receivables − payables)',   round(c_sum['total_outstanding'] - s_sum['total_outstanding'], 2)),
    ]
    for label, val in rows:
        ws.write(r, 0, label, cell)
        ws.write(r, 1, val, money if isinstance(val, float) else cell)
        r += 1

    r += 1
    ws.write(r, 0, 'Receivables aging', sub); ws.write(r, 1, '', sub); r += 1
    for b in AGING_BUCKETS:
        ws.write(r, 0, AGING_LABELS[b], cell); ws.write(r, 1, c_sum['aging'][b], money); r += 1
    r += 1
    ws.write(r, 0, 'Payables aging', sub); ws.write(r, 1, '', sub); r += 1
    for b in AGING_BUCKETS:
        ws.write(r, 0, AGING_LABELS[b], cell); ws.write(r, 1, s_sum['aging'][b], money); r += 1

    # ── Sheet 2/3: breakups ──────────────────────────────────────────────────
    def write_breakup(sheet_name, accounts, code_header, code_key):
        w = wb.add_worksheet(sheet_name)
        w.set_column('A:A', 6);  w.set_column('B:B', 26); w.set_column('C:C', 20)
        w.set_column('D:D', 14); w.set_column('E:I', 14); w.set_column('J:J', 18)
        w.write('A1', f'{sheet_name} — as on {today}', title)
        headers = ['#', 'Name', code_header, 'Mobile', 'Balance',
                   AGING_LABELS['current'], AGING_LABELS['d31_60'],
                   AGING_LABELS['d61_90'], AGING_LABELS['d90_plus'], 'Status']
        for c, h in enumerate(headers):
            w.write(2, c, h, hdr)
        rr = 3
        for i, a in enumerate(accounts, 1):
            w.write(rr, 0, i, cell)
            w.write(rr, 1, a['name'] or '', cell)
            w.write(rr, 2, a.get(code_key) or '', cell)
            w.write(rr, 3, a['mobile'] or '', cell)
            w.write(rr, 4, a['current_balance'], money)
            w.write(rr, 5, a['aging']['current'],  money)
            w.write(rr, 6, a['aging']['d31_60'],   money)
            w.write(rr, 7, a['aging']['d61_90'],   money)
            w.write(rr, 8, a['aging']['d90_plus'], money)
            w.write(rr, 9, 'OK' if a['reconciled'] else 'REVIEW', cell)
            rr += 1
        # Totals row
        w.write(rr, 0, '', cell); w.write(rr, 1, 'TOTAL', sub)
        w.write(rr, 2, '', sub);  w.write(rr, 3, '', sub)
        w.write(rr, 4, sum(a['current_balance'] for a in accounts if a['current_balance'] > 0), money_b)
        for ci, b in enumerate(AGING_BUCKETS, 5):
            w.write(rr, ci, sum(a['aging'][b] for a in accounts), money_b)
        w.write(rr, 9, '', sub)

    write_breakup('By Customer', customers, 'Customer Code', 'customer_code')
    write_breakup('By Supplier', suppliers, 'GSTIN',         'supplier_gst_number')

    wb.close()
    output.seek(0)
    filename = f"Credit_Report_{date.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )
