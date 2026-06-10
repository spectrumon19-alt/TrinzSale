from datetime import date, timedelta
import calendar
from flask import Blueprint, jsonify, request
from db import get_db_connection, release_db_connection
from auth import token_required
from psycopg2.extras import RealDictCursor

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard/kpis', methods=['GET'])
@token_required
def get_dashboard_kpis(payload):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Sales amounts shown to users are GST-INCLUSIVE (what the customer
        # actually paid = total_amount + total_gst), consistent with the
        # revenue charts, invoices and receipts. total_amount alone is ex-GST.

        # ── Today's sales ────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*)                                    AS invoice_count,
                COALESCE(SUM(total_amount + total_gst), 0)  AS total_amount,
                COALESCE(SUM(total_gst), 0)                 AS total_gst
            FROM sales_invoices
            WHERE status = 'Completed'
              AND DATE(invoice_date) = CURRENT_DATE
        """)
        today = cur.fetchone()

        # ── Yesterday (for % change) ─────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(SUM(total_amount + total_gst), 0) AS total_amount,
                COUNT(*)                                    AS invoice_count
            FROM sales_invoices
            WHERE status = 'Completed'
              AND DATE(invoice_date) = CURRENT_DATE - INTERVAL '1 day'
        """)
        yesterday = cur.fetchone()

        # ── This month's sales ───────────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(SUM(total_amount + total_gst), 0) AS total_amount,
                COUNT(*)                                    AS invoice_count
            FROM sales_invoices
            WHERE status = 'Completed'
              AND DATE_TRUNC('month', invoice_date) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        month = cur.fetchone()

        # ── Returns (net out of sales figures, GST-inclusive) ────────────────
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN return_date = CURRENT_DATE
                                  THEN total_amount + total_gst ELSE 0 END), 0) AS today_returns,
                COALESCE(SUM(CASE WHEN return_date = CURRENT_DATE
                                  THEN total_gst ELSE 0 END), 0)                AS today_returns_gst,
                COALESCE(SUM(CASE WHEN return_date = CURRENT_DATE - INTERVAL '1 day'
                                  THEN total_amount + total_gst ELSE 0 END), 0) AS yest_returns,
                COALESCE(SUM(CASE WHEN DATE_TRUNC('month', return_date)
                                       = DATE_TRUNC('month', CURRENT_DATE)
                                  THEN total_amount + total_gst ELSE 0 END), 0) AS month_returns
            FROM sales_returns
            WHERE status = 'Completed'
        """)
        ret = cur.fetchone()

        # Net = gross sales − returns (never below 0)
        today_amount   = max(0.0, float(today['total_amount'])    - float(ret['today_returns']))
        today_gst      = max(0.0, float(today['total_gst'])       - float(ret['today_returns_gst']))
        yest_amount    = max(0.0, float(yesterday['total_amount'])- float(ret['yest_returns']))
        month_amount   = max(0.0, float(month['total_amount'])    - float(ret['month_returns']))

        # ── Low-stock items (qty <= 10) ──────────────────────────────────────
        cur.execute("""
            SELECT COUNT(*) AS low_stock_count
            FROM products p
            JOIN inventory i ON p.product_id = i.product_id
            WHERE i.stock_quantity <= 10
        """)
        low_stock_row = cur.fetchone()

        cur.execute("""
            SELECT p.name, p.sku, i.stock_quantity
            FROM products p
            JOIN inventory i ON p.product_id = i.product_id
            WHERE i.stock_quantity <= 10
            ORDER BY i.stock_quantity ASC
            LIMIT 8
        """)
        low_stock_items = cur.fetchall()

        # ── Top 5 products today ─────────────────────────────────────────────
        cur.execute("""
            SELECT
                p.name,
                SUM(sii.quantity)          AS qty_sold,
                SUM(sii.total_line_amount) AS amount
            FROM sales_invoice_items sii
            JOIN products       p  ON sii.product_id = p.product_id
            JOIN sales_invoices si ON sii.invoice_id  = si.invoice_id
            WHERE si.status = 'Completed'
              AND DATE(si.invoice_date) = CURRENT_DATE
            GROUP BY p.product_id, p.name
            ORDER BY qty_sold DESC
            LIMIT 5
        """)
        top_products = cur.fetchall()

        # ── Recent 8 transactions (GST-inclusive grand total) ─────────────────
        cur.execute("""
            SELECT
                si.invoice_number,
                si.customer_name,
                (si.total_amount + si.total_gst) AS total_amount,
                si.invoice_date,
                si.mode_of_payment
            FROM sales_invoices si
            WHERE si.status = 'Completed'
            ORDER BY si.invoice_date DESC
            LIMIT 8
        """)
        recent_txns = cur.fetchall()
        # Serialise datetime
        for row in recent_txns:
            if row.get('invoice_date'):
                row['invoice_date'] = row['invoice_date'].strftime('%d %b %Y %H:%M')

        # ── Outstanding credit ───────────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*)                           AS credit_count,
                COALESCE(SUM(current_balance), 0)  AS total_outstanding
            FROM credit_customers
            WHERE current_balance > 0
        """)
        credit = cur.fetchone()

        # ── % change helpers ─────────────────────────────────────────────────
        def pct_change(today_val, yest_val):
            today_val = float(today_val or 0)
            yest_val  = float(yest_val  or 0)
            if yest_val == 0:
                return None
            return round(((today_val - yest_val) / yest_val) * 100, 1)

        return jsonify({
            'today': {
                'amount':        round(today_amount, 2),
                'invoice_count': int(today['invoice_count']),
                'gst':           round(today_gst, 2),
            },
            'yesterday': {
                'amount':        round(yest_amount, 2),
                'invoice_count': int(yesterday['invoice_count']),
            },
            'month': {
                'amount':        round(month_amount, 2),
                'invoice_count': int(month['invoice_count']),
            },
            'changes': {
                'amount_pct':  pct_change(today_amount, yest_amount),
                'invoice_pct': pct_change(today['invoice_count'], yesterday['invoice_count']),
            },
            'low_stock': {
                'count': int(low_stock_row['low_stock_count']),
                'items': [
                    {'name': r['name'], 'sku': r['sku'], 'stock_quantity': int(r['stock_quantity'])}
                    for r in low_stock_items
                ],
            },
            'top_products': [
                {'name': r['name'], 'qty_sold': int(r['qty_sold']), 'amount': float(r['amount'])}
                for r in top_products
            ],
            'recent_transactions': [
                {
                    'invoice_number': r['invoice_number'],
                    'customer_name':  r.get('customer_name') or '',
                    'total_amount':   float(r['total_amount']),
                    'invoice_date':   r['invoice_date'],
                    'mode_of_payment': r.get('mode_of_payment') or '',
                }
                for r in recent_txns
            ],
            'credit': {
                'count':       int(credit['credit_count']),
                'outstanding': float(credit['total_outstanding']),
            },
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@dashboard_bp.route('/dashboard/trends', methods=['GET'])
@token_required
def get_dashboard_trends(payload):
    try:
        days = int(request.args.get('days', 30))
        days = max(1, min(days, 90))
    except (ValueError, TypeError):
        days = 30

    today     = date.today()
    start_day = today - timedelta(days=days - 1)

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                DATE(invoice_date)              AS sale_date,
                COUNT(*)                        AS invoice_count,
                COALESCE(SUM(total_amount), 0)  AS total_amount,
                COALESCE(SUM(total_gst),    0)  AS total_gst
            FROM sales_invoices
            WHERE status = 'Completed'
              AND DATE(invoice_date) >= %s
            GROUP BY DATE(invoice_date)
            ORDER BY sale_date
        """, (start_day,))
        rows = cur.fetchall()
    finally:
        cur.close()
        release_db_connection(conn)

    # Index rows by date, then build a gapless date range (zeros for missing days)
    db_map = {}
    for row in rows:
        d = row['sale_date']
        if hasattr(d, 'date'):
            d = d.date()
        db_map[d] = row

    result = []
    cur_day = start_day
    while cur_day <= today:
        row = db_map.get(cur_day)
        # amount is GST-inclusive (total_amount + total_gst) for consistency
        # with the KPI cards, revenue charts and receipts; gst is shown separately.
        result.append({
            'date':          cur_day.isoformat(),
            'amount':        round(float(row['total_amount']) + float(row['total_gst']), 2) if row else 0.0,
            'invoice_count': int(row['invoice_count'])   if row else 0,
            'gst':           float(row['total_gst'])     if row else 0.0,
        })
        cur_day += timedelta(days=1)

    return jsonify({'days': days, 'data': result}), 200


# ── Advanced Analytics ──────────────────────────────────────────────────────

def _period_bounds(period: str):
    """Return (current_start, current_end, prev_start, prev_end) as date objects."""
    today = date.today()
    if period == 'week':
        wd = today.weekday()                          # 0=Mon
        cur_s  = today - timedelta(days=wd)
        cur_e  = today + timedelta(days=1)
        prev_s = cur_s - timedelta(weeks=1)
        prev_e = cur_s
    elif period == 'quarter':
        q      = (today.month - 1) // 3
        cur_s  = date(today.year, q * 3 + 1, 1)
        cur_e  = today + timedelta(days=1)
        if q == 0:
            prev_s = date(today.year - 1, 10, 1)
            prev_e = date(today.year, 1, 1)
        else:
            prev_s = date(today.year, (q - 1) * 3 + 1, 1)
            prev_e = cur_s
    elif period == 'year':
        cur_s  = date(today.year, 1, 1)
        cur_e  = today + timedelta(days=1)
        prev_s = date(today.year - 1, 1, 1)
        prev_e = date(today.year, 1, 1)
    else:  # month (default)
        cur_s  = date(today.year, today.month, 1)
        cur_e  = today + timedelta(days=1)
        if today.month == 1:
            prev_s = date(today.year - 1, 12, 1)
            prev_e = date(today.year, 1, 1)
        else:
            prev_s = date(today.year, today.month - 1, 1)
            prev_e = cur_s
    return cur_s, cur_e, prev_s, prev_e


def _daily_series(rows, start: date, end: date):
    """Build gapless daily series between start (inclusive) and end (exclusive)."""
    db_map = {}
    for r in rows:
        d = r['sale_date']
        if hasattr(d, 'date'):
            d = d.date()
        db_map[d] = r
    labels, revenue, inv_counts = [], [], []
    cur = start
    while cur < end:
        r = db_map.get(cur)
        labels.append(cur.strftime('%d %b'))
        revenue.append(float(r['revenue']) if r else 0.0)
        inv_counts.append(int(r['inv_count']) if r else 0)
        cur += timedelta(days=1)
    return labels, revenue, inv_counts


@dashboard_bp.route('/dashboard/advanced', methods=['GET'])
@token_required
def advanced_dashboard(payload):
    period   = request.args.get('period', 'month')
    cur_s, cur_e, prev_s, prev_e = _period_bounds(period)

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # ── Period KPIs ──────────────────────────────────────────────────────
        def period_kpis(start, end):
            cur.execute("""
                SELECT
                    COUNT(*)                                       AS inv_count,
                    COALESCE(SUM(total_amount + total_gst), 0)    AS revenue,
                    COALESCE(SUM(total_amount), 0)                AS taxable
                FROM sales_invoices
                WHERE status = 'Completed'
                  AND DATE(invoice_date) >= %s
                  AND DATE(invoice_date) < %s
            """, (start, end))
            return cur.fetchone()

        curr_kpi = period_kpis(cur_s, cur_e)
        prev_kpi = period_kpis(prev_s, prev_e)

        # Gross margin (taxable revenue − estimated purchase cost)
        cur.execute("""
            SELECT
                COALESCE(SUM(sii.exclusive_gst_amount), 0)          AS taxable_rev,
                COALESCE(SUM(sii.quantity * COALESCE(p.purchase_rate, 0)), 0) AS cost
            FROM sales_invoice_items sii
            JOIN products p ON sii.product_id = p.product_id
            JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
            WHERE si.status = 'Completed'
              AND DATE(si.invoice_date) >= %s
              AND DATE(si.invoice_date) < %s
        """, (cur_s, cur_e))
        margin_row  = cur.fetchone()
        tax_rev     = float(margin_row['taxable_rev'] or 0)
        cost        = float(margin_row['cost']        or 0)
        gross_margin_pct = round(((tax_rev - cost) / tax_rev * 100), 1) if tax_rev > 0 else 0.0

        c_rev  = float(curr_kpi['revenue'])
        p_rev  = float(prev_kpi['revenue'])
        c_inv  = int(curr_kpi['inv_count'])
        p_inv  = int(prev_kpi['inv_count'])

        def pct(a, b):
            return round((a - b) / b * 100, 1) if b else None

        avg_inv = round(c_rev / c_inv, 2) if c_inv else 0.0

        # ── Daily chart series ───────────────────────────────────────────────
        def daily_rows(start, end):
            cur.execute("""
                SELECT
                    DATE(invoice_date)                            AS sale_date,
                    COUNT(*)                                      AS inv_count,
                    COALESCE(SUM(total_amount + total_gst), 0)   AS revenue
                FROM sales_invoices
                WHERE status = 'Completed'
                  AND DATE(invoice_date) >= %s
                  AND DATE(invoice_date) < %s
                GROUP BY DATE(invoice_date)
                ORDER BY sale_date
            """, (start, end))
            return cur.fetchall()

        c_rows = daily_rows(cur_s, cur_e)
        p_rows = daily_rows(prev_s, prev_e)
        chart_labels, current_daily, current_counts = _daily_series(c_rows, cur_s, cur_e)
        prev_labels,  prev_daily,   _               = _daily_series(p_rows, prev_s, prev_e)

        # ── Payment mode breakdown ───────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(mode_of_payment), ''), 'Unknown') AS mode,
                COUNT(*)                                                AS inv_count,
                COALESCE(SUM(total_amount + total_gst), 0)             AS revenue
            FROM sales_invoices
            WHERE status = 'Completed'
              AND DATE(invoice_date) >= %s
              AND DATE(invoice_date) < %s
            GROUP BY mode
            ORDER BY revenue DESC
        """, (cur_s, cur_e))
        payment_rows = cur.fetchall()

        # ── GST rate breakdown ───────────────────────────────────────────────
        cur.execute("""
            SELECT
                sii.gst_rate_at_sale                       AS gst_rate,
                COALESCE(SUM(sii.cgst), 0)                 AS total_cgst,
                COALESCE(SUM(sii.sgst), 0)                 AS total_sgst,
                COALESCE(SUM(sii.exclusive_gst_amount), 0) AS taxable_value
            FROM sales_invoice_items sii
            JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
            WHERE si.status = 'Completed'
              AND DATE(si.invoice_date) >= %s
              AND DATE(si.invoice_date) < %s
            GROUP BY sii.gst_rate_at_sale
            ORDER BY gst_rate_at_sale
        """, (cur_s, cur_e))
        gst_rows = cur.fetchall()

        # ── Sales heatmap (last 90 days, hour × weekday) ─────────────────────
        # PostgreSQL DOW: 0=Sun → convert to 0=Mon
        cur.execute("""
            SELECT
                EXTRACT(HOUR FROM invoice_date)::int               AS hour,
                ((EXTRACT(DOW FROM invoice_date)::int + 6) % 7)    AS weekday,
                COUNT(*)                                            AS inv_count,
                COALESCE(SUM(total_amount + total_gst), 0)         AS revenue
            FROM sales_invoices
            WHERE status = 'Completed'
              AND invoice_date >= CURRENT_DATE - INTERVAL '90 days'
            GROUP BY hour, weekday
            ORDER BY hour, weekday
        """)
        hm_rows = cur.fetchall()

        # Build 24×7 matrices
        hm_count   = [[0]  * 7 for _ in range(24)]
        hm_revenue = [[0.0] * 7 for _ in range(24)]
        for r in hm_rows:
            h, d = int(r['hour']), int(r['weekday'])
            hm_count[h][d]   = int(r['inv_count'])
            hm_revenue[h][d] = float(r['revenue'])

        # ── Top 10 products by revenue ────────────────────────────────────────
        cur.execute("""
            SELECT
                p.name,
                SUM(sii.quantity)                                    AS qty_sold,
                COALESCE(SUM(sii.total_line_amount), 0)              AS revenue,
                ROUND(
                    CASE WHEN SUM(sii.exclusive_gst_amount) > 0
                    THEN ((SUM(sii.exclusive_gst_amount)
                           - SUM(sii.quantity * COALESCE(p.purchase_rate, 0)))
                          / NULLIF(SUM(sii.exclusive_gst_amount), 0)) * 100
                    ELSE 0 END
                , 1)                                                 AS margin_pct
            FROM sales_invoice_items sii
            JOIN products p ON sii.product_id = p.product_id
            JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
            WHERE si.status = 'Completed'
              AND DATE(si.invoice_date) >= %s
              AND DATE(si.invoice_date) < %s
            GROUP BY p.product_id, p.name
            ORDER BY revenue DESC
            LIMIT 10
        """, (cur_s, cur_e))
        product_rows = cur.fetchall()

        return jsonify({
            'period': period,
            'period_label': {
                'week': 'This Week', 'month': 'This Month',
                'quarter': 'This Quarter', 'year': 'This Year'
            }.get(period, 'This Month'),
            'kpis': {
                'current_revenue':    c_rev,
                'prev_revenue':       p_rev,
                'revenue_change_pct': pct(c_rev, p_rev),
                'current_invoices':   c_inv,
                'prev_invoices':      p_inv,
                'invoice_change_pct': pct(c_inv, p_inv),
                'avg_invoice_value':  avg_inv,
                'gross_margin_pct':   gross_margin_pct,
            },
            'chart': {
                'labels':         chart_labels,
                'current_daily':  current_daily,
                'current_counts': current_counts,
                'prev_labels':    prev_labels,
                'prev_daily':     prev_daily,
            },
            'payment_breakdown': [
                {'mode': r['mode'], 'count': int(r['inv_count']), 'revenue': float(r['revenue'])}
                for r in payment_rows
            ],
            'gst_breakdown': [
                {
                    'rate':          float(r['gst_rate']),
                    'cgst':          float(r['total_cgst']),
                    'sgst':          float(r['total_sgst']),
                    'taxable_value': float(r['taxable_value']),
                }
                for r in gst_rows
            ],
            'heatmap':         hm_count,
            'heatmap_revenue': hm_revenue,
            'top_products': [
                {
                    'name':       r['name'],
                    'qty_sold':   int(r['qty_sold']),
                    'revenue':    float(r['revenue']),
                    'margin_pct': float(r['margin_pct'] or 0),
                }
                for r in product_rows
            ],
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
