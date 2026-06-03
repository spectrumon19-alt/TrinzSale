from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required
from psycopg2.extras import RealDictCursor
import traceback

crm_bp = Blueprint('crm', __name__)


@crm_bp.route('/crm/stats', methods=['GET'])
@token_required
def get_crm_stats(payload):
    """Summary stats: total customers, active this month, revenue, top customer."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Total unique mobile-identified customers (union of credit + invoice customers)
        cur.execute("""
            SELECT COUNT(*) AS total FROM (
                SELECT mobile FROM credit_customers WHERE mobile IS NOT NULL AND mobile != ''
                UNION
                SELECT customer_mobile FROM sales_invoices
                WHERE customer_mobile IS NOT NULL AND customer_mobile != ''
            ) AS all_customers
        """)
        total_customers = cur.fetchone()['total']

        # Active this month (placed at least one non-cancelled invoice)
        cur.execute("""
            SELECT COUNT(DISTINCT customer_mobile) AS active
            FROM sales_invoices
            WHERE invoice_date >= DATE_TRUNC('month', CURRENT_DATE)
              AND status != 'Cancelled'
              AND customer_mobile IS NOT NULL AND customer_mobile != ''
        """)
        active_this_month = cur.fetchone()['active']

        # Total revenue from identified customers
        cur.execute("""
            SELECT COALESCE(SUM(total_amount), 0) AS revenue
            FROM sales_invoices
            WHERE customer_mobile IS NOT NULL AND customer_mobile != ''
              AND status != 'Cancelled'
        """)
        total_revenue = float(cur.fetchone()['revenue'])

        # Top customer by total spent
        cur.execute("""
            SELECT customer_mobile AS mobile,
                   MAX(customer_name) AS name,
                   SUM(total_amount) AS total_spent
            FROM sales_invoices
            WHERE customer_mobile IS NOT NULL AND customer_mobile != ''
              AND status != 'Cancelled'
            GROUP BY customer_mobile
            ORDER BY total_spent DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        top_customer = None
        if row:
            # Prefer credit_customers name if available
            cur.execute("""
                SELECT name FROM credit_customers WHERE mobile = %s LIMIT 1
            """, (row['mobile'],))
            cc = cur.fetchone()
            top_customer = {
                'name': cc['name'] if cc else row['name'],
                'mobile': row['mobile'],
                'total_spent': float(row['total_spent'])
            }

        # Total credit customers count
        cur.execute("SELECT COUNT(*) AS cnt FROM credit_customers")
        credit_count = cur.fetchone()['cnt']

        return jsonify({
            'total_customers': total_customers,
            'active_this_month': active_this_month,
            'total_revenue': total_revenue,
            'credit_customers': credit_count,
            'top_customer': top_customer
        }), 200

    except Exception as e:
        print(f"CRM stats error: {e}\n{traceback.format_exc()}")
        return jsonify({'message': 'Failed to fetch stats', 'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: release_db_connection(conn)


@crm_bp.route('/crm/customers', methods=['GET'])
@token_required
def list_crm_customers(payload):
    """
    Unified customer list: credit customers UNION walk-in customers from invoices.
    Query params: search, type (all/credit/walkin), page, per_page, sort (spent/invoices/recent/name)
    """
    search   = request.args.get('search', '').strip()
    ctype    = request.args.get('type', 'all')       # all | credit | walkin
    page     = max(1, int(request.args.get('page', 1)))
    per_page = min(100, max(10, int(request.args.get('per_page', 25))))
    sort     = request.args.get('sort', 'spent')      # spent | invoices | recent | name

    sort_clause = {
        'spent':    'total_spent DESC NULLS LAST',
        'invoices': 'total_invoices DESC NULLS LAST',
        'recent':   'last_purchase DESC NULLS LAST',
        'name':     'customer_name ASC',
    }.get(sort, 'total_spent DESC NULLS LAST')

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build base CTE
        base_cte = """
            WITH invoice_stats AS (
                SELECT
                    customer_mobile                    AS mobile,
                    MAX(customer_name)                 AS inv_name,
                    COUNT(invoice_id)                  AS total_invoices,
                    SUM(total_amount)                  AS total_spent,
                    MAX(invoice_date)                  AS last_purchase,
                    AVG(total_amount)                  AS avg_order
                FROM sales_invoices
                WHERE customer_mobile IS NOT NULL AND customer_mobile != ''
                  AND status != 'Cancelled'
                GROUP BY customer_mobile
            ),
            unified AS (
                -- Credit customers (always included, even if no invoices yet)
                SELECT
                    cc.name                            AS customer_name,
                    cc.mobile,
                    'credit'                           AS customer_type,
                    cc.customer_id,
                    cc.customer_code,
                    cc.email,
                    cc.address,
                    cc.current_balance,
                    cc.created_at                      AS registered_at,
                    COALESCE(ist.total_invoices, 0)    AS total_invoices,
                    COALESCE(ist.total_spent, 0)       AS total_spent,
                    ist.last_purchase,
                    ist.avg_order
                FROM credit_customers cc
                LEFT JOIN invoice_stats ist ON ist.mobile = cc.mobile

                UNION ALL

                -- Walk-in customers: in invoices but NOT in credit_customers
                SELECT
                    ist.inv_name                       AS customer_name,
                    ist.mobile,
                    'walkin'                           AS customer_type,
                    NULL                               AS customer_id,
                    NULL                               AS customer_code,
                    NULL                               AS email,
                    NULL                               AS address,
                    NULL                               AS current_balance,
                    NULL                               AS registered_at,
                    ist.total_invoices,
                    ist.total_spent,
                    ist.last_purchase,
                    ist.avg_order
                FROM invoice_stats ist
                LEFT JOIN credit_customers cc ON cc.mobile = ist.mobile
                WHERE cc.customer_id IS NULL
            )
        """

        # WHERE conditions
        conditions = []
        params = []
        if search:
            conditions.append("(customer_name ILIKE %s OR mobile ILIKE %s)")
            params += [f'%{search}%', f'%{search}%']
        if ctype == 'credit':
            conditions.append("customer_type = 'credit'")
        elif ctype == 'walkin':
            conditions.append("customer_type = 'walkin'")

        where_sql = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        # Count total
        count_sql = f"{base_cte} SELECT COUNT(*) AS total FROM unified {where_sql}"
        cur.execute(count_sql, params)
        total_count = cur.fetchone()['total']

        # Fetch page
        offset = (page - 1) * per_page
        data_sql = f"""
            {base_cte}
            SELECT * FROM unified
            {where_sql}
            ORDER BY {sort_clause}
            LIMIT %s OFFSET %s
        """
        cur.execute(data_sql, params + [per_page, offset])
        rows = cur.fetchall()

        customers = []
        for r in rows:
            customers.append({
                'name':           r['customer_name'],
                'mobile':         r['mobile'],
                'type':           r['customer_type'],
                'customer_id':    r['customer_id'],
                'customer_code':  r['customer_code'],
                'email':          r['email'],
                'address':        r['address'],
                'current_balance': float(r['current_balance']) if r['current_balance'] is not None else None,
                'registered_at':  r['registered_at'].isoformat() if r['registered_at'] else None,
                'total_invoices': int(r['total_invoices'] or 0),
                'total_spent':    float(r['total_spent'] or 0),
                'last_purchase':  r['last_purchase'].isoformat() if r['last_purchase'] else None,
                'avg_order':      float(r['avg_order']) if r['avg_order'] else None,
            })

        return jsonify({
            'customers': customers,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'pages': max(1, -(-total_count // per_page)),
        }), 200

    except Exception as e:
        print(f"CRM list error: {e}\n{traceback.format_exc()}")
        return jsonify({'message': 'Failed to fetch customers', 'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: release_db_connection(conn)


@crm_bp.route('/crm/customers/<mobile>/history', methods=['GET'])
@token_required
def get_customer_history(payload, mobile):
    """Full purchase history for a customer identified by mobile number."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Credit customer profile (if exists)
        cur.execute("""
            SELECT customer_id, customer_code, name, mobile, email, address,
                   current_balance, created_at
            FROM credit_customers
            WHERE mobile = %s
            LIMIT 1
        """, (mobile,))
        credit_profile = cur.fetchone()

        # All invoices for this mobile
        cur.execute("""
            SELECT invoice_id, invoice_number, invoice_date, customer_name,
                   total_amount, total_gst, discount_amount, mode_of_payment,
                   status
            FROM sales_invoices
            WHERE customer_mobile = %s
            ORDER BY invoice_date DESC
        """, (mobile,))
        invoices = cur.fetchall()

        # Invoice items for each invoice (batch fetch)
        invoice_ids = [inv['invoice_id'] for inv in invoices]
        items_by_invoice = {}
        if invoice_ids:
            cur.execute("""
                SELECT sii.invoice_id, p.name AS product_name, p.pack_size,
                       sii.quantity, sii.rate_at_sale, sii.total_line_amount
                FROM sales_invoice_items sii
                JOIN products p ON p.product_id = sii.product_id
                WHERE sii.invoice_id = ANY(%s)
                ORDER BY sii.item_id
            """, (invoice_ids,))
            for item in cur.fetchall():
                items_by_invoice.setdefault(item['invoice_id'], []).append({
                    'product_name': item['product_name'],
                    'pack_size':    item['pack_size'],
                    'quantity':     item['quantity'],
                    'rate':         float(item['rate_at_sale']),
                    'total':        float(item['total_line_amount']),
                })

        invoices_out = []
        for inv in invoices:
            invoices_out.append({
                'invoice_id':     inv['invoice_id'],
                'invoice_number': inv['invoice_number'],
                'invoice_date':   inv['invoice_date'].isoformat(),
                'customer_name':  inv['customer_name'],
                'total_amount':   float(inv['total_amount']),
                'total_gst':      float(inv['total_gst']),
                'discount_amount':float(inv['discount_amount'] or 0),
                'payment_mode':   inv['mode_of_payment'],
                'status':         inv['status'],
                'items':          items_by_invoice.get(inv['invoice_id'], []),
            })

        # Credit transactions (only if credit customer)
        credit_transactions = []
        if credit_profile:
            cur.execute("""
                SELECT transaction_id, transaction_type, amount, invoice_no,
                       note, previous_balance, created_at
                FROM credit_transactions
                WHERE customer_id = %s
                ORDER BY created_at DESC
            """, (credit_profile['customer_id'],))
            for tx in cur.fetchall():
                credit_transactions.append({
                    'transaction_id':   tx['transaction_id'],
                    'type':             tx['transaction_type'],
                    'amount':           float(tx['amount']),
                    'invoice_no':       tx['invoice_no'],
                    'note':             tx['note'],
                    'previous_balance': float(tx['previous_balance']),
                    'created_at':       tx['created_at'].isoformat(),
                })

        # Aggregate stats from invoices
        completed = [i for i in invoices_out if i['status'] != 'Cancelled']
        total_spent  = sum(i['total_amount'] for i in completed)
        avg_order    = total_spent / len(completed) if completed else 0
        first_purchase = min((i['invoice_date'] for i in completed), default=None)
        last_purchase  = max((i['invoice_date'] for i in completed), default=None)

        profile = None
        if credit_profile:
            profile = {
                'customer_id':     credit_profile['customer_id'],
                'customer_code':   credit_profile['customer_code'],
                'name':            credit_profile['name'],
                'mobile':          credit_profile['mobile'],
                'email':           credit_profile['email'],
                'address':         credit_profile['address'],
                'current_balance': float(credit_profile['current_balance'] or 0),
                'registered_at':   credit_profile['created_at'].isoformat() if credit_profile['created_at'] else None,
            }

        return jsonify({
            'mobile':              mobile,
            'profile':             profile,
            'invoices':            invoices_out,
            'credit_transactions': credit_transactions,
            'stats': {
                'total_invoices':  len(invoices_out),
                'total_spent':     round(total_spent, 2),
                'avg_order':       round(avg_order, 2),
                'first_purchase':  first_purchase,
                'last_purchase':   last_purchase,
            }
        }), 200

    except Exception as e:
        print(f"CRM history error: {e}\n{traceback.format_exc()}")
        return jsonify({'message': 'Failed to fetch customer history', 'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: release_db_connection(conn)
