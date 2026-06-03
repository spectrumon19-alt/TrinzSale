from flask import Blueprint, request, Response, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required
from psycopg2.extras import RealDictCursor
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

tally_export_bp = Blueprint('tally_export', __name__)


def _fmt_date(dt):
    if hasattr(dt, 'strftime'):
        return dt.strftime('%Y%m%d')
    return datetime.fromisoformat(str(dt)).strftime('%Y%m%d')


def _ledger_entry(parent, ledger_name, is_debit, amount):
    """Append one ALLLEDGERENTRIES.LIST node. Debit = negative amount in Tally."""
    entry = ET.SubElement(parent, 'ALLLEDGERENTRIES.LIST')
    ET.SubElement(entry, 'LEDGERNAME').text = ledger_name
    ET.SubElement(entry, 'ISDEEMEDPOSITIVE').text = 'Yes' if is_debit else 'No'
    signed = -abs(float(amount)) if is_debit else abs(float(amount))
    ET.SubElement(entry, 'AMOUNT').text = f'{signed:.2f}'


def _build_envelope():
    root = ET.Element('ENVELOPE')
    header = ET.SubElement(root, 'HEADER')
    ET.SubElement(header, 'TALLYREQUEST').text = 'Import Data'
    body = ET.SubElement(root, 'BODY')
    imp = ET.SubElement(body, 'IMPORTDATA')
    desc = ET.SubElement(imp, 'REQUESTDESC')
    ET.SubElement(desc, 'REPORTNAME').text = 'Vouchers'
    req_data = ET.SubElement(imp, 'REQUESTDATA')
    return root, req_data


def _add_sales_vouchers(req_data, rows, lm):
    for inv in rows:
        msg = ET.SubElement(req_data, 'TALLYMESSAGE')
        msg.set('xmlns:UDF', 'TallyUDF')
        v = ET.SubElement(msg, 'VOUCHER')
        v.set('VCHTYPE', 'Sales')
        v.set('ACTION', 'Create')

        ET.SubElement(v, 'DATE').text = _fmt_date(inv['invoice_date'])
        ET.SubElement(v, 'VOUCHERTYPENAME').text = 'Sales'
        ET.SubElement(v, 'VOUCHERNUMBER').text = str(inv['invoice_number'])

        mode = (inv.get('mode_of_payment') or 'Cash').lower()
        if 'upi' in mode or 'online' in mode:
            party = lm['upi']
        elif 'credit' in mode:
            party = inv.get('customer_name') or 'Sundry Debtors'
        else:
            party = lm['cash']

        ET.SubElement(v, 'PARTYLEDGERNAME').text = party
        narr = f"Invoice: {inv['invoice_number']}"
        if inv.get('customer_name'):
            narr += f" | {inv['customer_name']}"
        ET.SubElement(v, 'NARRATION').text = narr

        total = float(inv['total_amount'])
        cgst  = float(inv['total_cgst'] or 0)
        sgst  = float(inv['total_sgst'] or 0)
        taxable = total - cgst - sgst

        _ledger_entry(v, party,      True,  total)
        _ledger_entry(v, lm['sales'], False, taxable)
        if cgst: _ledger_entry(v, lm['out_cgst'], False, cgst)
        if sgst: _ledger_entry(v, lm['out_sgst'], False, sgst)


def _add_purchase_vouchers(req_data, rows, lm):
    for po in rows:
        msg = ET.SubElement(req_data, 'TALLYMESSAGE')
        msg.set('xmlns:UDF', 'TallyUDF')
        v = ET.SubElement(msg, 'VOUCHER')
        v.set('VCHTYPE', 'Purchase')
        v.set('ACTION', 'Create')

        ET.SubElement(v, 'DATE').text = _fmt_date(po['purchase_date'])
        ET.SubElement(v, 'VOUCHERTYPENAME').text = 'Purchase'
        ET.SubElement(v, 'VOUCHERNUMBER').text = str(po['purchase_order_number'])

        supplier = po.get('supplier_name') or 'Sundry Creditors'
        ET.SubElement(v, 'PARTYLEDGERNAME').text = supplier
        ET.SubElement(v, 'NARRATION').text = f"Purchase: {po['purchase_order_number']}"

        total   = float(po['total_amount'])
        cgst    = float(po['total_cgst'] or 0)
        sgst    = float(po['total_sgst'] or 0)
        taxable = total - cgst - sgst

        _ledger_entry(v, lm['purchases'],  True,  taxable)
        if cgst: _ledger_entry(v, lm['in_cgst'], True, cgst)
        if sgst: _ledger_entry(v, lm['in_sgst'], True, sgst)
        _ledger_entry(v, supplier, False, total)


def _add_return_vouchers(req_data, rows, lm):
    for ret in rows:
        msg = ET.SubElement(req_data, 'TALLYMESSAGE')
        msg.set('xmlns:UDF', 'TallyUDF')
        v = ET.SubElement(msg, 'VOUCHER')
        v.set('VCHTYPE', 'Credit Note')
        v.set('ACTION', 'Create')

        ET.SubElement(v, 'DATE').text = _fmt_date(ret['return_date'])
        ET.SubElement(v, 'VOUCHERTYPENAME').text = 'Credit Note'
        ET.SubElement(v, 'VOUCHERNUMBER').text = str(ret['return_number'])

        mode = (ret.get('refund_method') or 'Cash').lower()
        party = lm['upi'] if 'upi' in mode else lm['cash']

        ET.SubElement(v, 'PARTYLEDGERNAME').text = party
        ET.SubElement(v, 'NARRATION').text = f"Return: {ret['return_number']} | Ref: {ret['original_invoice_number']}"

        total   = float(ret['total_amount'])
        cgst    = float(ret['total_cgst'] or 0)
        sgst    = float(ret['total_sgst'] or 0)
        taxable = total - cgst - sgst

        _ledger_entry(v, lm['sales'], True,  taxable)
        if cgst: _ledger_entry(v, lm['out_cgst'], True, cgst)
        if sgst: _ledger_entry(v, lm['out_sgst'], True, sgst)
        _ledger_entry(v, party, False, total)


def _prettify(root):
    raw = ET.tostring(root, encoding='unicode')
    return minidom.parseString(raw).toprettyxml(indent='  ', encoding=None)


@tally_export_bp.route('/tally/export', methods=['GET'])
@token_required
def export_tally(payload):
    export_type = request.args.get('type', 'sales')   # sales | purchase | returns | all
    from_date   = request.args.get('from_date')
    to_date     = request.args.get('to_date')

    # Ledger names — defaults match standard Tally chart of accounts
    lm = {
        'cash':      request.args.get('l_cash',      'Cash'),
        'upi':       request.args.get('l_upi',       'UPI Receipts'),
        'sales':     request.args.get('l_sales',     'Sales'),
        'out_cgst':  request.args.get('l_out_cgst',  'Output CGST'),
        'out_sgst':  request.args.get('l_out_sgst',  'Output SGST'),
        'purchases': request.args.get('l_purchases', 'Purchases'),
        'in_cgst':   request.args.get('l_in_cgst',   'Input CGST'),
        'in_sgst':   request.args.get('l_in_sgst',   'Input SGST'),
    }

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)

    try:
        root, req_data = _build_envelope()

        date_filter_si  = []
        date_filter_po  = []
        date_filter_ret = []
        params_si = params_po = params_ret = []

        def date_params(alias_date):
            p = []
            f = ''
            if from_date:
                f += f' AND DATE({alias_date}) >= %s'
                p.append(from_date)
            if to_date:
                f += f' AND DATE({alias_date}) <= %s'
                p.append(to_date)
            return f, p

        # ── Sales ─────────────────────────────────────────────────
        if export_type in ('sales', 'all'):
            df, p = date_params('si.invoice_date')
            cur.execute(f"""
                SELECT si.invoice_number, si.invoice_date, si.customer_name,
                       si.mode_of_payment, si.total_amount,
                       COALESCE(SUM(ii.cgst), si.total_gst/2) AS total_cgst,
                       COALESCE(SUM(ii.sgst), si.total_gst/2) AS total_sgst
                FROM sales_invoices si
                LEFT JOIN sales_invoice_items ii ON ii.invoice_id = si.invoice_id
                WHERE si.status = 'Completed' {df}
                GROUP BY si.invoice_id
                ORDER BY si.invoice_date
            """, p)
            _add_sales_vouchers(req_data, cur.fetchall(), lm)

        # ── Purchases ─────────────────────────────────────────────
        if export_type in ('purchase', 'all'):
            df, p = date_params('po.purchase_date')
            cur.execute(f"""
                SELECT po.purchase_order_number, po.purchase_date, po.supplier_name,
                       po.total_amount,
                       COALESCE(SUM(poi.cgst), 0) AS total_cgst,
                       COALESCE(SUM(poi.sgst), 0) AS total_sgst
                FROM purchase_orders po
                LEFT JOIN purchase_order_items poi ON poi.purchase_order_id = po.purchase_order_id
                WHERE po.status = 'Completed' {df}
                GROUP BY po.purchase_order_id
                ORDER BY po.purchase_date
            """, p)
            _add_purchase_vouchers(req_data, cur.fetchall(), lm)

        # ── Returns ───────────────────────────────────────────────
        if export_type in ('returns', 'all'):
            df, p = date_params('sr.return_date')
            cur.execute(f"""
                SELECT sr.return_number, sr.return_date, sr.original_invoice_number,
                       sr.refund_method, sr.total_amount,
                       COALESCE(SUM(ri.cgst), sr.total_gst/2) AS total_cgst,
                       COALESCE(SUM(ri.sgst), sr.total_gst/2) AS total_sgst
                FROM sales_returns sr
                LEFT JOIN sales_return_items ri ON ri.return_id = sr.return_id
                WHERE sr.status = 'Completed' {df}
                GROUP BY sr.return_id
                ORDER BY sr.return_date
            """, p)
            _add_return_vouchers(req_data, cur.fetchall(), lm)

        xml_str  = _prettify(root)
        ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'tally_{export_type}_{ts}.xml'

        return Response(
            xml_str,
            mimetype='application/xml',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
