import logging
from datetime import date, datetime

from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor

from auth import token_required, admin_required
from db import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)
returns_bp = Blueprint('returns', __name__)

RETURN_REASONS = [
    'Damaged Product', 'Wrong Item Delivered', 'Customer Changed Mind',
    'Quality Issue', 'Duplicate Order', 'Other'
]
REFUND_METHODS = ['Cash', 'Store Credit', 'UPI', 'Original Payment']


def _next_return_number(cur):
    today = datetime.utcnow().strftime('%Y%m%d')
    cur.execute(
        "SELECT COUNT(*) FROM sales_returns WHERE return_number LIKE %s",
        (f'RET-{today}-%',)
    )
    row = cur.fetchone()
    # RealDictCursor returns a dict; get the single value regardless of column name
    count = int(next(iter(row.values()), 0)) if row else 0
    return f'RET-{today}-{count + 1:04d}'


def _calc_line(rate, qty, discount_pct, gst_rate):
    base          = rate * qty
    after_disc    = base * (1 - discount_pct / 100)
    gst_amount    = round(after_disc * gst_rate / 100, 2)
    sgst          = round(gst_amount / 2, 2)
    cgst          = round(gst_amount - sgst, 2)
    total         = round(after_disc + gst_amount, 2)
    excl_gst      = round(after_disc, 2)
    return dict(exclusive_gst_amount=excl_gst, sgst=sgst, cgst=cgst,
                total_line_amount=total, total_gst=gst_amount)


# ── GET /api/sales-invoices/<id>/returnable ───────────────────────────────────
@returns_bp.route('/sales-invoices/<int:invoice_id>/returnable', methods=['GET'])
@token_required
def get_returnable_items(payload, invoice_id):
    """Return invoice header + each item's returnable quantity."""
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT si.invoice_id, si.invoice_number, si.invoice_date,
                   si.customer_name, si.customer_mobile, si.mode_of_payment,
                   si.total_amount, si.total_gst,
                   (si.total_amount + si.total_gst) AS grand_total,
                   si.status
            FROM sales_invoices si
            WHERE si.invoice_id = %s
        """, (invoice_id,))
        invoice = cur.fetchone()
        if not invoice:
            return jsonify({'message': 'Invoice not found'}), 404
        if invoice['status'] == 'Cancelled':
            return jsonify({'message': 'Cannot return a cancelled invoice'}), 400

        cur.execute("""
            SELECT
                sii.item_id,
                sii.product_id,
                p.name        AS product_name,
                p.sku,
                p.pack_size,
                sii.quantity  AS original_qty,
                sii.rate_at_sale,
                sii.discount_percentage,
                sii.gst_rate_at_sale,
                sii.total_line_amount,
                COALESCE((
                    SELECT SUM(sri.quantity)
                    FROM   sales_return_items sri
                    WHERE  sri.original_item_id = sii.item_id
                ), 0) AS already_returned,
                sii.quantity - COALESCE((
                    SELECT SUM(sri.quantity)
                    FROM   sales_return_items sri
                    WHERE  sri.original_item_id = sii.item_id
                ), 0) AS returnable_qty
            FROM sales_invoice_items sii
            JOIN products p ON p.product_id = sii.product_id
            WHERE sii.invoice_id = %s
            ORDER BY sii.item_id
        """, (invoice_id,))
        items = cur.fetchall()

        return jsonify({'invoice': dict(invoice), 'items': [dict(i) for i in items]}), 200
    except Exception as e:
        logger.exception("Get returnable items error")
        return jsonify({"message": f"Failed to fetch invoice: {e}"}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/sales-invoices/search ───────────────────────────────────────────
@returns_bp.route('/sales-invoices/search', methods=['GET'])
@token_required
def search_invoices_for_return(payload):
    """Search completed invoices by invoice_number or customer_mobile."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'message': 'q parameter required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT invoice_id, invoice_number, invoice_date,
                   customer_name, customer_mobile, mode_of_payment,
                   total_amount, total_gst,
                   (total_amount + total_gst) AS grand_total, status
            FROM sales_invoices
            WHERE status = 'Completed'
              AND (invoice_number ILIKE %s OR customer_mobile ILIKE %s)
            ORDER BY invoice_date DESC
            LIMIT 20
        """, (f'%{q}%', f'%{q}%'))
        rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        logger.exception("Invoice search error")
        return jsonify({"message": f"Search failed: {e}"}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── POST /api/returns ─────────────────────────────────────────────────────────
@returns_bp.route('/returns', methods=['POST'])
@admin_required
def create_return(payload):
    """
    Body:
      original_invoice_id  int
      return_reason        str
      refund_method        str
      notes                str (optional)
      items: [{original_item_id, product_id, quantity}]
    """
    user_id = payload['user_id']
    data    = request.get_json() or {}

    invoice_id    = data.get('original_invoice_id')
    return_reason = (data.get('return_reason') or '').strip()
    refund_method = (data.get('refund_method') or '').strip()
    notes         = (data.get('notes') or '').strip() or None
    items         = data.get('items', [])

    if not invoice_id:
        return jsonify({'message': 'original_invoice_id is required'}), 400
    if not return_reason:
        return jsonify({'message': 'return_reason is required'}), 400
    if refund_method not in REFUND_METHODS:
        return jsonify({'message': f'refund_method must be one of: {", ".join(REFUND_METHODS)}'}), 400
    if not items:
        return jsonify({'message': 'At least one item is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Verify invoice
        cur.execute("""
            SELECT invoice_id, invoice_number, customer_name, customer_mobile, status
            FROM sales_invoices WHERE invoice_id = %s
        """, (invoice_id,))
        invoice = cur.fetchone()
        if not invoice:
            return jsonify({'message': 'Invoice not found'}), 404
        if invoice['status'] == 'Cancelled':
            return jsonify({'message': 'Cannot return a cancelled invoice'}), 400

        return_number = _next_return_number(cur)
        subtotal = total_gst = total_amount = 0.0
        line_inserts = []

        for item in items:
            orig_item_id = item.get('original_item_id')
            qty          = int(item.get('quantity', 0))
            if qty <= 0:
                continue

            # Load original item
            cur.execute("""
                SELECT sii.item_id, sii.product_id, sii.rate_at_sale,
                       sii.gst_rate_at_sale, sii.discount_percentage,
                       sii.quantity AS original_qty,
                       p.name AS product_name, p.sku, p.pack_size,
                       COALESCE((
                           SELECT SUM(sri.quantity)
                           FROM   sales_return_items sri
                           WHERE  sri.original_item_id = sii.item_id
                       ), 0) AS already_returned
                FROM sales_invoice_items sii
                JOIN products p ON p.product_id = sii.product_id
                WHERE sii.item_id = %s AND sii.invoice_id = %s
            """, (orig_item_id, invoice_id))
            orig = cur.fetchone()
            if not orig:
                return jsonify({'message': f'Item {orig_item_id} not found in invoice'}), 400

            returnable = orig['original_qty'] - orig['already_returned']
            if qty > returnable:
                return jsonify({
                    'message': f'Cannot return {qty} of "{orig["product_name"]}" — only {returnable} returnable'
                }), 400

            calc = _calc_line(
                float(orig['rate_at_sale']), qty,
                float(orig['discount_percentage']),
                float(orig['gst_rate_at_sale'])
            )
            subtotal     += calc['exclusive_gst_amount']
            total_gst    += calc['total_gst']
            total_amount += calc['total_line_amount']

            line_inserts.append({
                'orig_item_id':  orig_item_id,
                'product_id':    orig['product_id'],
                'product_name':  orig['product_name'],
                'sku':           orig['sku'],
                'pack_size':     orig['pack_size'],
                'quantity':      qty,
                'rate':          float(orig['rate_at_sale']),
                'discount_pct':  float(orig['discount_percentage']),
                'gst_rate':      float(orig['gst_rate_at_sale']),
                **calc
            })

        if not line_inserts:
            return jsonify({'message': 'No valid items to return'}), 400

        # Insert return header
        cur.execute("""
            INSERT INTO sales_returns
              (return_number, original_invoice_id, original_invoice_number,
               return_date, customer_name, customer_mobile,
               return_reason, refund_method,
               subtotal, total_gst, total_amount,
               status, user_id, notes)
            VALUES (%s,%s,%s, CURRENT_DATE, %s,%s, %s,%s, %s,%s,%s, 'Completed', %s,%s)
            RETURNING return_id
        """, (
            return_number, invoice_id, invoice['invoice_number'],
            invoice['customer_name'], invoice['customer_mobile'],
            return_reason, refund_method,
            round(subtotal, 2), round(total_gst, 2), round(total_amount, 2),
            user_id, notes
        ))
        return_id = cur.fetchone()['return_id']

        # Insert items + restore inventory
        for li in line_inserts:
            cur.execute("""
                INSERT INTO sales_return_items
                  (return_id, original_item_id, product_id,
                   product_name, sku, pack_size, quantity,
                   rate_at_return, discount_percentage, gst_rate,
                   exclusive_gst_amount, sgst, cgst, total_line_amount)
                VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s)
            """, (
                return_id, li['orig_item_id'], li['product_id'],
                li['product_name'], li['sku'], li['pack_size'], li['quantity'],
                li['rate'], li['discount_pct'], li['gst_rate'],
                li['exclusive_gst_amount'], li['sgst'], li['cgst'],
                li['total_line_amount']
            ))

            # Restore stock
            cur.execute("""
                UPDATE inventory
                SET stock_quantity = stock_quantity + %s
                WHERE product_id = %s
            """, (li['quantity'], li['product_id']))

        conn.commit()
        logger.info("Return %s created (invoice %s)", return_number, invoice['invoice_number'])
        return jsonify({
            'message':       'Return processed successfully',
            'return_id':     return_id,
            'return_number': return_number,
            'total_amount':  round(total_amount, 2)
        }), 201

    except Exception as e:
        conn.rollback()
        logger.exception("Create return error")
        return jsonify({'message': f'Failed to process return: {e}'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/returns ──────────────────────────────────────────────────────────
@returns_bp.route('/returns', methods=['GET'])
@token_required
def list_returns(payload):
    from_date = request.args.get('from_date')
    to_date   = request.args.get('to_date')

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query  = """
            SELECT sr.return_id, sr.return_number, sr.return_date,
                   sr.original_invoice_number, sr.customer_name, sr.customer_mobile,
                   sr.return_reason, sr.refund_method,
                   sr.subtotal, sr.total_gst, sr.total_amount,
                   sr.status, sr.notes, sr.created_at,
                   u.username AS processed_by
            FROM   sales_returns sr
            LEFT JOIN users u ON u.user_id = sr.user_id
            WHERE  1=1
        """
        params = []
        if from_date:
            query += " AND sr.return_date >= %s"; params.append(from_date)
        if to_date:
            query += " AND sr.return_date <= %s"; params.append(to_date)
        query += " ORDER BY sr.created_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        logger.exception("List returns error")
        return jsonify({"message": f"Failed to fetch returns: {e}"}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── GET /api/returns/<id> ─────────────────────────────────────────────────────
@returns_bp.route('/returns/<int:return_id>', methods=['GET'])
@token_required
def get_return(payload, return_id):
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT sr.*, u.username AS processed_by
            FROM   sales_returns sr
            LEFT JOIN users u ON u.user_id = sr.user_id
            WHERE  sr.return_id = %s
        """, (return_id,))
        ret = cur.fetchone()
        if not ret:
            return jsonify({'message': 'Return not found'}), 404

        cur.execute("""
            SELECT * FROM sales_return_items WHERE return_id = %s ORDER BY return_item_id
        """, (return_id,))
        items = cur.fetchall()

        return jsonify({'return': dict(ret), 'items': [dict(i) for i in items]}), 200
    except Exception as e:
        logger.exception("Get return error")
        return jsonify({"message": f"Failed to fetch return: {e}"}), 500
    finally:
        cur.close()
        release_db_connection(conn)
