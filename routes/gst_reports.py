from flask import Blueprint, jsonify, request, send_file
from db import get_db_connection, release_db_connection
from auth import token_required
from psycopg2.extras import RealDictCursor
import io
from datetime import datetime

gst_reports_bp = Blueprint('gst_reports', __name__)


def _period_clause(period: str):
    """Return (sql_fragment, param) for filtering by YYYY-MM period."""
    try:
        dt = datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise ValueError(f"Invalid period format '{period}'. Use YYYY-MM.")
    return "DATE_TRUNC('month', %s::date)", f"{period}-01"


def _fetch_gstr1(cur, period: str) -> dict:
    """Return all GSTR-1 data for the given period."""
    trunc_sql, param = _period_clause(period)

    # ── Rate-wise outward supply summary ────────────────────────────────────
    cur.execute(f"""
        SELECT
            sii.gst_rate_at_sale                    AS gst_rate,
            COUNT(DISTINCT si.invoice_id)           AS invoice_count,
            COALESCE(SUM(sii.exclusive_gst_amount), 0) AS taxable_value,
            COALESCE(SUM(sii.sgst), 0)              AS sgst,
            COALESCE(SUM(sii.cgst), 0)              AS cgst
        FROM sales_invoice_items sii
        JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
        WHERE si.status = 'Completed'
          AND DATE_TRUNC('month', si.invoice_date) = {trunc_sql}
        GROUP BY sii.gst_rate_at_sale
        ORDER BY sii.gst_rate_at_sale
    """, (param,))
    rate_rows = cur.fetchall()

    rate_summary = []
    total_taxable = total_sgst = total_cgst = 0
    for r in rate_rows:
        tv  = float(r['taxable_value'])
        sg  = float(r['sgst'])
        cg  = float(r['cgst'])
        total_taxable += tv
        total_sgst    += sg
        total_cgst    += cg
        rate_summary.append({
            'gst_rate':      float(r['gst_rate']),
            'invoice_count': int(r['invoice_count']),
            'taxable_value': round(tv, 2),
            'sgst':          round(sg, 2),
            'cgst':          round(cg, 2),
            'total_gst':     round(sg + cg, 2),
            'gross_value':   round(tv + sg + cg, 2),
        })

    # ── Invoice list (B2C — all, since no customer GSTIN in schema) ─────────
    cur.execute(f"""
        SELECT
            si.invoice_number,
            si.invoice_date,
            si.customer_name,
            si.customer_mobile,
            si.mode_of_payment,
            COALESCE(si.discount_amount, 0)           AS discount_amount,
            si.total_gst,
            si.total_amount,
            (si.total_amount - si.total_gst)          AS taxable_value
        FROM sales_invoices si
        WHERE si.status = 'Completed'
          AND DATE_TRUNC('month', si.invoice_date) = {trunc_sql}
        ORDER BY si.invoice_date, si.invoice_id
    """, (param,))
    inv_rows = cur.fetchall()

    invoices = []
    for r in inv_rows:
        invoices.append({
            'invoice_number': r['invoice_number'],
            'invoice_date':   r['invoice_date'].strftime('%d-%b-%Y'),
            'customer_name':  r['customer_name'] or 'Retail',
            'customer_mobile': r['customer_mobile'] or '',
            'mode_of_payment': r['mode_of_payment'] or '',
            'discount_amount': float(r['discount_amount']),
            'taxable_value':  round(float(r['taxable_value']), 2),
            'total_gst':      float(r['total_gst']),
            'total_amount':   float(r['total_amount']),
        })

    # ── Credit notes (sales returns) — reduce outward liability ─────────────
    # Returns are reported in the period the return occurred (return_date),
    # which is standard credit-note treatment under GST.
    cur.execute(f"""
        SELECT
            sri.gst_rate                            AS gst_rate,
            COUNT(DISTINCT sr.return_id)            AS note_count,
            COALESCE(SUM(sri.exclusive_gst_amount), 0) AS taxable_value,
            COALESCE(SUM(sri.sgst), 0)              AS sgst,
            COALESCE(SUM(sri.cgst), 0)              AS cgst
        FROM sales_return_items sri
        JOIN sales_returns sr ON sri.return_id = sr.return_id
        WHERE sr.status = 'Completed'
          AND DATE_TRUNC('month', sr.return_date) = {trunc_sql}
        GROUP BY sri.gst_rate
        ORDER BY sri.gst_rate
    """, (param,))
    cn_rows = cur.fetchall()

    credit_notes = []
    cn_taxable = cn_sgst = cn_cgst = 0
    for r in cn_rows:
        tv = float(r['taxable_value'])
        sg = float(r['sgst'])
        cg = float(r['cgst'])
        cn_taxable += tv
        cn_sgst    += sg
        cn_cgst    += cg
        credit_notes.append({
            'gst_rate':      float(r['gst_rate']),
            'note_count':    int(r['note_count']),
            'taxable_value': round(tv, 2),
            'sgst':          round(sg, 2),
            'cgst':          round(cg, 2),
            'total_gst':     round(sg + cg, 2),
            'gross_value':   round(tv + sg + cg, 2),
        })

    # ── Credit note (return) invoice-level list ─────────────────────────────
    cur.execute(f"""
        SELECT
            sr.return_number,
            sr.original_invoice_number,
            sr.return_date,
            sr.customer_name,
            sr.customer_mobile,
            sr.return_reason,
            sr.subtotal      AS taxable_value,
            sr.total_gst,
            sr.total_amount
        FROM sales_returns sr
        WHERE sr.status = 'Completed'
          AND DATE_TRUNC('month', sr.return_date) = {trunc_sql}
        ORDER BY sr.return_date, sr.return_id
    """, (param,))
    cn_list_rows = cur.fetchall()

    credit_note_list = []
    for r in cn_list_rows:
        credit_note_list.append({
            'return_number':           r['return_number'],
            'original_invoice_number': r['original_invoice_number'],
            'return_date':             r['return_date'].strftime('%d-%b-%Y'),
            'customer_name':           r['customer_name'] or 'Retail',
            'customer_mobile':         r['customer_mobile'] or '',
            'return_reason':           r['return_reason'] or '',
            'taxable_value':           round(float(r['taxable_value']), 2),
            'total_gst':               float(r['total_gst']),
            'total_amount':            float(r['total_amount']),
        })

    # Net figures = outward supplies − credit notes
    net_taxable = total_taxable - cn_taxable
    net_sgst    = total_sgst - cn_sgst
    net_cgst    = total_cgst - cn_cgst

    return {
        'period':          period,
        'rate_summary':    rate_summary,
        'invoices':        invoices,
        'invoice_count':   len(invoices),
        'total_taxable':   round(total_taxable, 2),
        'total_sgst':      round(total_sgst, 2),
        'total_cgst':      round(total_cgst, 2),
        'total_gst':       round(total_sgst + total_cgst, 2),
        'grand_total':     round(total_taxable + total_sgst + total_cgst, 2),
        # Credit notes (sales returns) for the period
        'credit_notes':       credit_notes,
        'credit_note_list':   credit_note_list,
        'credit_note_count':  len(credit_note_list),
        'cn_total_taxable':   round(cn_taxable, 2),
        'cn_total_sgst':      round(cn_sgst, 2),
        'cn_total_cgst':      round(cn_cgst, 2),
        'cn_total_gst':       round(cn_sgst + cn_cgst, 2),
        # Net outward liability after credit notes
        'net_taxable':     round(net_taxable, 2),
        'net_sgst':        round(net_sgst, 2),
        'net_cgst':        round(net_cgst, 2),
        'net_gst':         round(net_sgst + net_cgst, 2),
        'net_grand_total': round(net_taxable + net_sgst + net_cgst, 2),
    }


def _fetch_gstr3b(cur, period: str) -> dict:
    """Return GSTR-3B summary data for the given period."""
    trunc_sql, param = _period_clause(period)

    # ── 3.1 Outward taxable supplies ────────────────────────────────────────
    cur.execute(f"""
        SELECT
            COALESCE(SUM(sii.exclusive_gst_amount), 0) AS taxable_value,
            COALESCE(SUM(sii.sgst), 0)                 AS sgst,
            COALESCE(SUM(sii.cgst), 0)                 AS cgst,
            COUNT(DISTINCT si.invoice_id)              AS invoice_count
        FROM sales_invoice_items sii
        JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
        WHERE si.status = 'Completed'
          AND DATE_TRUNC('month', si.invoice_date) = {trunc_sql}
    """, (param,))
    out = cur.fetchone()
    out_taxable = float(out['taxable_value'])
    out_sgst    = float(out['sgst'])
    out_cgst    = float(out['cgst'])
    out_invoices = int(out['invoice_count'])

    # ── 3.1 by rate (for detailed breakdown) ────────────────────────────────
    cur.execute(f"""
        SELECT
            sii.gst_rate_at_sale                       AS gst_rate,
            COALESCE(SUM(sii.exclusive_gst_amount), 0) AS taxable_value,
            COALESCE(SUM(sii.sgst), 0)                 AS sgst,
            COALESCE(SUM(sii.cgst), 0)                 AS cgst
        FROM sales_invoice_items sii
        JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
        WHERE si.status = 'Completed'
          AND DATE_TRUNC('month', si.invoice_date) = {trunc_sql}
        GROUP BY sii.gst_rate_at_sale
        ORDER BY sii.gst_rate_at_sale
    """, (param,))
    out_by_rate = [
        {
            'gst_rate':      float(r['gst_rate']),
            'taxable_value': round(float(r['taxable_value']), 2),
            'sgst':          round(float(r['sgst']), 2),
            'cgst':          round(float(r['cgst']), 2),
            'total_gst':     round(float(r['sgst']) + float(r['cgst']), 2),
        }
        for r in cur.fetchall()
    ]

    # ── Credit notes (sales returns) — reduce outward supplies ──────────────
    cur.execute(f"""
        SELECT
            COALESCE(SUM(sri.exclusive_gst_amount), 0) AS taxable_value,
            COALESCE(SUM(sri.sgst), 0)                 AS sgst,
            COALESCE(SUM(sri.cgst), 0)                 AS cgst,
            COUNT(DISTINCT sr.return_id)               AS note_count
        FROM sales_return_items sri
        JOIN sales_returns sr ON sri.return_id = sr.return_id
        WHERE sr.status = 'Completed'
          AND DATE_TRUNC('month', sr.return_date) = {trunc_sql}
    """, (param,))
    cn = cur.fetchone()
    cn_taxable    = float(cn['taxable_value'])
    cn_sgst       = float(cn['sgst'])
    cn_cgst       = float(cn['cgst'])
    cn_notes      = int(cn['note_count'])

    # Net outward (after credit notes) — what actually goes on GSTR-3B 3.1
    net_out_taxable = out_taxable - cn_taxable
    net_out_sgst    = out_sgst - cn_sgst
    net_out_cgst    = out_cgst - cn_cgst

    # ── 4(A) ITC from purchases ──────────────────────────────────────────────
    cur.execute(f"""
        SELECT
            COALESCE(SUM(poi.sgst), 0) AS itc_sgst,
            COALESCE(SUM(poi.cgst), 0) AS itc_cgst,
            COUNT(DISTINCT po.purchase_order_id) AS po_count
        FROM purchase_order_items poi
        JOIN purchase_orders po ON poi.purchase_order_id = po.purchase_order_id
        WHERE po.status = 'Completed'
          AND DATE_TRUNC('month', po.purchase_date) = {trunc_sql}
    """, (param,))
    itc = cur.fetchone()
    itc_sgst = float(itc['itc_sgst'])
    itc_cgst = float(itc['itc_cgst'])
    po_count = int(itc['po_count'])

    # ── Net tax payable = (outward tax − credit notes) – ITC ────────────────
    net_sgst = max(0.0, net_out_sgst - itc_sgst)
    net_cgst = max(0.0, net_out_cgst - itc_cgst)

    return {
        'period': period,
        # 3.1 Outward supplies (gross, before credit notes)
        'outward': {
            'invoice_count': out_invoices,
            'taxable_value': round(out_taxable, 2),
            'sgst':          round(out_sgst, 2),
            'cgst':          round(out_cgst, 2),
            'total_gst':     round(out_sgst + out_cgst, 2),
            'grand_total':   round(out_taxable + out_sgst + out_cgst, 2),
            'by_rate':       out_by_rate,
        },
        # Credit notes (sales returns) reducing outward supplies
        'credit_notes': {
            'note_count':    cn_notes,
            'taxable_value': round(cn_taxable, 2),
            'sgst':          round(cn_sgst, 2),
            'cgst':          round(cn_cgst, 2),
            'total_gst':     round(cn_sgst + cn_cgst, 2),
            'grand_total':   round(cn_taxable + cn_sgst + cn_cgst, 2),
        },
        # 3.1 Net outward supplies (after credit notes) — the figure to file
        'net_outward': {
            'taxable_value': round(net_out_taxable, 2),
            'sgst':          round(net_out_sgst, 2),
            'cgst':          round(net_out_cgst, 2),
            'total_gst':     round(net_out_sgst + net_out_cgst, 2),
            'grand_total':   round(net_out_taxable + net_out_sgst + net_out_cgst, 2),
        },
        # 4 ITC available
        'itc': {
            'po_count':  po_count,
            'sgst':      round(itc_sgst, 2),
            'cgst':      round(itc_cgst, 2),
            'total_gst': round(itc_sgst + itc_cgst, 2),
        },
        # 6.1 Net tax payable = net outward tax − ITC
        'net_payable': {
            'sgst':      round(net_sgst, 2),
            'cgst':      round(net_cgst, 2),
            'total':     round(net_sgst + net_cgst, 2),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# API endpoints
# ════════════════════════════════════════════════════════════════════════════

@gst_reports_bp.route('/gst/gstr1', methods=['GET'])
@token_required
def get_gstr1(payload):
    period = request.args.get('period', '').strip()
    if not period:
        from datetime import date
        period = date.today().strftime('%Y-%m')
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        data = _fetch_gstr1(cur, period)
        return jsonify(data), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@gst_reports_bp.route('/gst/gstr3b', methods=['GET'])
@token_required
def get_gstr3b(payload):
    period = request.args.get('period', '').strip()
    if not period:
        from datetime import date
        period = date.today().strftime('%Y-%m')
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        data = _fetch_gstr3b(cur, period)
        return jsonify(data), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@gst_reports_bp.route('/gst/export/excel', methods=['GET'])
@token_required
def export_gst_excel(payload):
    period = request.args.get('period', '').strip()
    if not period:
        from datetime import date
        period = date.today().strftime('%Y-%m')

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        g1   = _fetch_gstr1(cur, period)
        g3b  = _fetch_gstr3b(cur, period)
    except ValueError as e:
        cur.close(); release_db_connection(conn)
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        cur.close(); release_db_connection(conn)
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

    try:
        import xlsxwriter
    except ImportError:
        return jsonify({'error': 'xlsxwriter not installed. Run: pip install xlsxwriter'}), 500

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})

    # ── Formats ──────────────────────────────────────────────────────────────
    hdr   = wb.add_format({'bold': True, 'bg_color': '#1d4ed8', 'font_color': '#ffffff',
                           'border': 1, 'font_size': 9, 'align': 'center', 'valign': 'vcenter'})
    title = wb.add_format({'bold': True, 'font_size': 13, 'font_color': '#1d4ed8'})
    sub   = wb.add_format({'bold': True, 'font_size': 10, 'bg_color': '#eff6ff',
                           'border': 1, 'font_color': '#1e40af'})
    cell  = wb.add_format({'border': 1, 'font_size': 9, 'valign': 'vcenter'})
    money = wb.add_format({'border': 1, 'font_size': 9, 'num_format': '₹#,##0.00',
                           'align': 'right'})
    total_fmt = wb.add_format({'bold': True, 'border': 1, 'font_size': 9,
                               'num_format': '₹#,##0.00', 'align': 'right',
                               'bg_color': '#dbeafe'})
    pct   = wb.add_format({'border': 1, 'font_size': 9, 'num_format': '0.00"%"',
                           'align': 'center'})

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 1 — GSTR-1 Rate-wise Summary
    # ════════════════════════════════════════════════════════════════════════
    ws1 = wb.add_worksheet('GSTR-1 Summary')
    ws1.set_column('A:A', 14); ws1.set_column('B:B', 14)
    ws1.set_column('C:G', 16)

    ws1.write('A1', f'GSTR-1 — Outward Supplies Summary   Period: {period}', title)
    ws1.write('A2', 'TrintzPOS — Auto-generated')
    ws1.set_row(3, 18)

    headers = ['GST Rate %', 'Invoice Count', 'Taxable Value (₹)',
               'SGST (₹)', 'CGST (₹)', 'Total GST (₹)', 'Gross Value (₹)']
    for c, h in enumerate(headers):
        ws1.write(3, c, h, hdr)

    for i, r in enumerate(g1['rate_summary'], start=4):
        ws1.write(i, 0, r['gst_rate'],      cell)
        ws1.write(i, 1, r['invoice_count'],  cell)
        ws1.write(i, 2, r['taxable_value'],  money)
        ws1.write(i, 3, r['sgst'],           money)
        ws1.write(i, 4, r['cgst'],           money)
        ws1.write(i, 5, r['total_gst'],      money)
        ws1.write(i, 6, r['gross_value'],    money)

    tr = 4 + len(g1['rate_summary'])
    ws1.write(tr, 0, 'TOTAL', sub)
    ws1.write(tr, 1, g1['invoice_count'],  total_fmt)
    ws1.write(tr, 2, g1['total_taxable'],  total_fmt)
    ws1.write(tr, 3, g1['total_sgst'],     total_fmt)
    ws1.write(tr, 4, g1['total_cgst'],     total_fmt)
    ws1.write(tr, 5, g1['total_gst'],      total_fmt)
    ws1.write(tr, 6, g1['grand_total'],    total_fmt)

    # Credit notes (sales returns) — shown as negative, reducing liability
    cn_row = tr + 2
    ws1.write(cn_row, 0, 'Less: Credit Notes (Sales Returns)', sub)
    cn_row += 1
    for c, h in enumerate(['GST Rate %', 'Note Count', 'Taxable Value (₹)',
                           'SGST (₹)', 'CGST (₹)', 'Total GST (₹)', 'Gross Value (₹)']):
        ws1.write(cn_row, c, h, hdr)
    cn_row += 1
    for r in g1['credit_notes']:
        ws1.write(cn_row, 0, r['gst_rate'],            cell)
        ws1.write(cn_row, 1, r['note_count'],          cell)
        ws1.write(cn_row, 2, -r['taxable_value'],      money)
        ws1.write(cn_row, 3, -r['sgst'],               money)
        ws1.write(cn_row, 4, -r['cgst'],               money)
        ws1.write(cn_row, 5, -r['total_gst'],          money)
        ws1.write(cn_row, 6, -r['gross_value'],        money)
        cn_row += 1
    ws1.write(cn_row, 0, 'CREDIT NOTE TOTAL', sub)
    ws1.write(cn_row, 1, g1['credit_note_count'], total_fmt)
    ws1.write(cn_row, 2, -g1['cn_total_taxable'], total_fmt)
    ws1.write(cn_row, 3, -g1['cn_total_sgst'],    total_fmt)
    ws1.write(cn_row, 4, -g1['cn_total_cgst'],    total_fmt)
    ws1.write(cn_row, 5, -g1['cn_total_gst'],     total_fmt)
    ws1.write(cn_row, 6, -(g1['cn_total_taxable'] + g1['cn_total_gst']), total_fmt)
    cn_row += 1

    # Net outward supplies after credit notes
    ws1.write(cn_row, 0, 'NET OUTWARD (after credit notes)', sub)
    ws1.write(cn_row, 1, '',                  total_fmt)
    ws1.write(cn_row, 2, g1['net_taxable'],   total_fmt)
    ws1.write(cn_row, 3, g1['net_sgst'],      total_fmt)
    ws1.write(cn_row, 4, g1['net_cgst'],      total_fmt)
    ws1.write(cn_row, 5, g1['net_gst'],       total_fmt)
    ws1.write(cn_row, 6, g1['net_grand_total'], total_fmt)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 2 — GSTR-1 Invoice List
    # ════════════════════════════════════════════════════════════════════════
    ws2 = wb.add_worksheet('GSTR-1 Invoices')
    ws2.set_column('A:A', 6); ws2.set_column('B:B', 20)
    ws2.set_column('C:C', 14); ws2.set_column('D:D', 22)
    ws2.set_column('E:E', 14); ws2.set_column('F:F', 14)
    ws2.set_column('G:I', 14); ws2.set_column('J:J', 12)

    ws2.write('A1', f'GSTR-1 — B2C Invoice List   Period: {period}', title)
    ws2.set_row(2, 18)
    inv_headers = ['#', 'Invoice Number', 'Date', 'Customer',
                   'Mobile', 'Payment', 'Taxable Value (₹)',
                   'Total GST (₹)', 'Invoice Total (₹)', 'Discount (₹)']
    for c, h in enumerate(inv_headers):
        ws2.write(2, c, h, hdr)

    for i, inv in enumerate(g1['invoices'], start=3):
        ws2.write(i, 0, i - 2,                cell)
        ws2.write(i, 1, inv['invoice_number'], cell)
        ws2.write(i, 2, inv['invoice_date'],   cell)
        ws2.write(i, 3, inv['customer_name'],  cell)
        ws2.write(i, 4, inv['customer_mobile'],cell)
        ws2.write(i, 5, inv['mode_of_payment'],cell)
        ws2.write(i, 6, inv['taxable_value'],  money)
        ws2.write(i, 7, inv['total_gst'],      money)
        ws2.write(i, 8, inv['total_amount'],   money)
        ws2.write(i, 9, inv['discount_amount'],money)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 2b — GSTR-1 Credit Notes (Sales Returns)
    # ════════════════════════════════════════════════════════════════════════
    ws2b = wb.add_worksheet('GSTR-1 Credit Notes')
    ws2b.set_column('A:A', 6);  ws2b.set_column('B:B', 20)
    ws2b.set_column('C:C', 20); ws2b.set_column('D:D', 14)
    ws2b.set_column('E:E', 22); ws2b.set_column('F:F', 14)
    ws2b.set_column('G:G', 20); ws2b.set_column('H:J', 16)

    ws2b.write('A1', f'GSTR-1 — Credit Notes (Sales Returns)   Period: {period}', title)
    ws2b.set_row(2, 18)
    cn_headers = ['#', 'Credit Note No', 'Orig. Invoice', 'Date', 'Customer',
                  'Mobile', 'Reason', 'Taxable Value (₹)', 'Total GST (₹)', 'Note Total (₹)']
    for c, h in enumerate(cn_headers):
        ws2b.write(2, c, h, hdr)

    for i, cnr in enumerate(g1['credit_note_list'], start=3):
        ws2b.write(i, 0, i - 2,                       cell)
        ws2b.write(i, 1, cnr['return_number'],         cell)
        ws2b.write(i, 2, cnr['original_invoice_number'],cell)
        ws2b.write(i, 3, cnr['return_date'],           cell)
        ws2b.write(i, 4, cnr['customer_name'],         cell)
        ws2b.write(i, 5, cnr['customer_mobile'],       cell)
        ws2b.write(i, 6, cnr['return_reason'],         cell)
        ws2b.write(i, 7, -cnr['taxable_value'],        money)
        ws2b.write(i, 8, -cnr['total_gst'],            money)
        ws2b.write(i, 9, -cnr['total_amount'],         money)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 3 — GSTR-3B Summary
    # ════════════════════════════════════════════════════════════════════════
    ws3 = wb.add_worksheet('GSTR-3B')
    ws3.set_column('A:A', 42); ws3.set_column('B:E', 16)

    ws3.write('A1', f'GSTR-3B — Monthly Self-Assessment Return   Period: {period}', title)
    ws3.write('A2', 'TrintzPOS — Auto-generated')

    row = 3
    def section(label):
        nonlocal row
        ws3.merge_range(row, 0, row, 4, label, sub)
        row += 1

    def line(label, sgst, cgst, total=None):
        nonlocal row
        if total is None:
            total = sgst + cgst
        ws3.write(row, 0, label, cell)
        ws3.write(row, 1, '',    cell)
        ws3.write(row, 2, sgst,  money)
        ws3.write(row, 3, cgst,  money)
        ws3.write(row, 4, total, money)
        row += 1

    col_headers = ['Description', 'Taxable Value (₹)', 'SGST (₹)', 'CGST (₹)', 'Total Tax (₹)']
    ws3.set_row(row, 18)
    for c, h in enumerate(col_headers):
        ws3.write(row, c, h, hdr)
    row += 1

    section('3.1  Details of Outward Supplies and Inward Supplies liable to Reverse Charge')
    out = g3b['outward']
    cn  = g3b['credit_notes']
    net_out = g3b['net_outward']
    ws3.write(row, 0, '(a) Outward taxable supplies (gross, before credit notes)', cell)
    ws3.write(row, 1, out['taxable_value'], money)
    ws3.write(row, 2, out['sgst'],          money)
    ws3.write(row, 3, out['cgst'],          money)
    ws3.write(row, 4, out['total_gst'],     money); row += 1

    ws3.write(row, 0, 'Less: Credit Notes / Sales Returns', cell)
    ws3.write(row, 1, -cn['taxable_value'], money)
    ws3.write(row, 2, -cn['sgst'],          money)
    ws3.write(row, 3, -cn['cgst'],          money)
    ws3.write(row, 4, -cn['total_gst'],     money); row += 1

    ws3.write(row, 0, '(a) Net outward taxable supplies (to be reported)', sub)
    ws3.write(row, 1, net_out['taxable_value'], total_fmt)
    ws3.write(row, 2, net_out['sgst'],          total_fmt)
    ws3.write(row, 3, net_out['cgst'],          total_fmt)
    ws3.write(row, 4, net_out['total_gst'],     total_fmt); row += 1

    ws3.write(row, 0, '(b) Zero rated supplies',             cell)
    for c in range(1, 5): ws3.write(row, c, 0.00, money); row += 1
    ws3.write(row, 0, '(c) Nil rated and exempted supplies', cell)
    for c in range(1, 5): ws3.write(row, c, 0.00, money); row += 1
    ws3.write(row, 0, '(d) Inward supplies (liable to reverse charge)', cell)
    for c in range(1, 5): ws3.write(row, c, 0.00, money); row += 1

    row += 1
    section('4.  Eligible ITC (Input Tax Credit)')
    itc = g3b['itc']
    ws3.write(row, 0, '(A)(5) All other ITC — from Purchase Invoices this period', cell)
    ws3.write(row, 1, '',              cell)
    ws3.write(row, 2, itc['sgst'],     money)
    ws3.write(row, 3, itc['cgst'],     money)
    ws3.write(row, 4, itc['total_gst'],money); row += 1

    row += 1
    section('5.  Values of Exempt, Nil-Rated and Non-GST Inward Supplies')
    ws3.write(row, 0, '(Not applicable — all supplies are GST taxable)', cell)
    for c in range(1, 5): ws3.write(row, c, 0.00, money); row += 2

    section('6.1  Payment of Tax')
    net = g3b['net_payable']
    ws3.write(row, 0, 'Tax payable (Net Outward GST − ITC)', cell)
    ws3.write(row, 1, '',              cell)
    ws3.write(row, 2, net['sgst'],     total_fmt)
    ws3.write(row, 3, net['cgst'],     total_fmt)
    ws3.write(row, 4, net['total'],    total_fmt); row += 1

    wb.close()
    output.seek(0)

    filename = f"GST_Report_{period}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )
