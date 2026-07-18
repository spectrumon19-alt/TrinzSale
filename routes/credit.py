from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required
from psycopg2.extras import RealDictCursor
from ledger_utils import find_recent_duplicate
import uuid
import traceback
import io
import csv
from datetime import datetime

def generate_customer_code(customer_name, conn):
    """Generate customer code in format: first 2 letters of name + YYMMDD + serial number"""
    # Get first 2 letters of customer name (uppercase)
    name_prefix = customer_name[:2].upper() if len(customer_name) >= 2 else customer_name.upper().ljust(2, 'X')
    
    # Get current date in YYMMDD format
    current_date = datetime.now().strftime('%y%m%d')
    
    # Generate base customer code
    base_customer_code = f"{name_prefix}{current_date}"
    
    # Find the next serial number for this date
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT customer_code FROM credit_customers 
            WHERE customer_code LIKE %s 
            ORDER BY customer_code DESC 
            LIMIT 1
        """, (f"{base_customer_code}%",))
        
        existing_customer = cur.fetchone()
        
        if existing_customer:
            # Extract the serial number from the last customer code
            last_code = existing_customer['customer_code']
            try:
                last_serial = int(last_code[-3:])  # Last 3 digits
                serial_number = last_serial + 1
            except:
                serial_number = 1
        else:
            serial_number = 1
        
        # Format the customer code with leading zeros
        customer_code = f"{base_customer_code}{serial_number:03d}"
        return customer_code
    finally:
        cur.close()

credit_bp = Blueprint('credit', __name__)

@credit_bp.route('/customers', methods=['POST'])
@admin_required
def create_credit_customer(payload):
    """Create a new credit customer"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name') or not data.get('mobile'):
            return jsonify({'message': 'Name and mobile are required'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Generate a unique customer UUID
            customer_uuid = str(uuid.uuid4())
            
            # Generate customer code
            customer_name = data.get('name', '')
            customer_code = generate_customer_code(customer_name, conn)
            
            # Insert new customer
            cur.execute("""
                INSERT INTO credit_customers (
                    customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING customer_id, customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance, created_at
            """, (
                customer_code,
                customer_uuid,
                data.get('name'),
                data.get('mobile'),
                data.get('email') or None,
                data.get('address') or None,
                data.get('invoice_no') or None,
                data.get('initial_balance', 0)
            ))
            
            customer = cur.fetchone()
            
            # Commit transaction
            conn.commit()
            
            return jsonify({
                'message': 'Customer created successfully',
                'customer': customer
            }), 201
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Create credit customer error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to create customer', 'error': str(e)}), 500

@credit_bp.route('/customers/lookup-email', methods=['GET'])
@token_required
def lookup_customer_email(payload):
    mobile = (request.args.get('mobile') or '').strip()
    if not mobile:
        return jsonify({'email': None})
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT email FROM credit_customers WHERE mobile = %s AND email IS NOT NULL AND email != '' LIMIT 1", (mobile,))
        row = cur.fetchone()
        return jsonify({'email': row[0] if row else None})
    finally:
        cur.close()
        release_db_connection(conn)

@credit_bp.route('/customers', methods=['GET'])
@admin_required
def get_credit_customers(payload):
    """Get all credit customers with optional search"""
    try:
        # Get query parameters
        search = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Build query based on search
            if search:
                cur.execute("""
                    SELECT customer_id, customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance, created_at
                    FROM credit_customers
                    WHERE name ILIKE %s OR mobile ILIKE %s OR customer_code ILIKE %s OR customer_uuid ILIKE %s
                    ORDER BY name
                    LIMIT %s OFFSET %s
                """, (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%', per_page, (page - 1) * per_page))
            else:
                cur.execute("""
                    SELECT customer_id, customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance, created_at
                    FROM credit_customers
                    ORDER BY name
                    LIMIT %s OFFSET %s
                """, (per_page, (page - 1) * per_page))
            
            customers = cur.fetchall()
            
            # Ensure current_balance is a float for consistency
            for customer in customers:
                if 'current_balance' in customer and customer['current_balance'] is not None:
                    customer['current_balance'] = float(customer['current_balance'])
            
            # Get total count
            if search:
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM credit_customers
                    WHERE name ILIKE %s OR mobile ILIKE %s OR customer_code ILIKE %s OR customer_uuid ILIKE %s
                """, (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%'))
            else:
                cur.execute("SELECT COUNT(*) as count FROM credit_customers")
            
            count_result = cur.fetchone()
            total = count_result['count'] if count_result else 0
            
            return jsonify({
                'customers': customers,
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page
            }), 200
            
        except Exception as e:
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Get credit customers error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to fetch customers', 'error': str(e)}), 500

@credit_bp.route('/customers/<int:customer_id>', methods=['GET'])
@admin_required
def get_credit_customer(payload, customer_id):
    """Get a specific credit customer by ID"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Get customer details
            cur.execute("""
                SELECT customer_id, customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance, created_at
                FROM credit_customers
                WHERE customer_id = %s
            """, (customer_id,))
            
            customer = cur.fetchone()
            if not customer:
                return jsonify({'message': 'Customer not found'}), 404
            
            # Get customer transactions
            cur.execute("""
                SELECT transaction_id, transaction_type, amount, invoice_no, note, previous_balance, created_at
                FROM credit_transactions
                WHERE customer_id = %s
                ORDER BY created_at DESC
            """, (customer_id,))
            
            transactions = cur.fetchall()
            
            # Convert amount to float to ensure it's a number in JSON
            for transaction in transactions:
                transaction['amount'] = float(transaction['amount'])
            
            # Ensure current_balance is a float for consistency
            if customer and 'current_balance' in customer and customer['current_balance'] is not None:
                customer['current_balance'] = float(customer['current_balance'])
            
            # Add transactions to customer object
            customer_dict = dict(customer)
            customer_dict['transactions'] = transactions
            
            return jsonify(customer_dict), 200
            
        except Exception as e:
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Get credit customer error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to fetch customer', 'error': str(e)}), 500

@credit_bp.route('/customers/<int:customer_id>', methods=['PUT'])
@admin_required
def update_credit_customer(payload, customer_id):
    """Update a credit customer"""
    try:
        data = request.get_json()
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Check if customer exists
            cur.execute("""
                SELECT customer_id FROM credit_customers WHERE customer_id = %s
            """, (customer_id,))
            
            if not cur.fetchone():
                return jsonify({'message': 'Customer not found'}), 404
            
            # Update customer
            cur.execute("""
                UPDATE credit_customers
                SET name = %s, mobile = %s, email = %s, address = %s, invoice_no = %s, updated_at = %s
                WHERE customer_id = %s
            """, (
                data.get('name'),
                data.get('mobile'),
                data.get('email') or None,
                data.get('address') or None,
                data.get('invoice_no') or None,
                datetime.now(),
                customer_id
            ))
            
            # Commit transaction
            conn.commit()
            
            # Get updated customer
            cur.execute("""
                SELECT customer_id, customer_code, customer_uuid, name, mobile, email, address, invoice_no, current_balance, created_at
                FROM credit_customers
                WHERE customer_id = %s
            """, (customer_id,))
            
            customer = cur.fetchone()
            
            # Ensure current_balance is a float for consistency
            if customer and 'current_balance' in customer and customer['current_balance'] is not None:
                customer['current_balance'] = float(customer['current_balance'])
            
            return jsonify({
                'message': 'Customer updated successfully',
                'customer': customer
            }), 200
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Update credit customer error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to update customer', 'error': str(e)}), 500

@credit_bp.route('/customers/<int:customer_id>', methods=['DELETE'])
@admin_required
def delete_credit_customer(payload, customer_id):
    """Delete a credit customer"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Check if customer exists
            cur.execute("""
                SELECT customer_id FROM credit_customers WHERE customer_id = %s
            """, (customer_id,))
            
            if not cur.fetchone():
                return jsonify({'message': 'Customer not found'}), 404
            
            # Delete customer (cascades to transactions)
            cur.execute("""
                DELETE FROM credit_customers WHERE customer_id = %s
            """, (customer_id,))
            
            # Commit transaction
            conn.commit()
            
            return jsonify({'message': 'Customer deleted successfully'}), 200
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Delete credit customer error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to delete customer', 'error': str(e)}), 500

@credit_bp.route('/customers/<int:customer_id>/transactions', methods=['POST'])
@admin_required
def add_credit_transaction(payload, customer_id):
    """Add a credit transaction for a customer"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('transaction_type') or not data.get('amount'):
            return jsonify({'message': 'Transaction type and amount are required'}), 400
        
        if data.get('transaction_type') not in ['credit', 'debit']:
            return jsonify({'message': 'Transaction type must be either credit or debit'}), 400
        
        if float(data.get('amount', 0)) <= 0:
            return jsonify({'message': 'Amount must be greater than 0'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Get customer's current balance
            cur.execute("""
                SELECT current_balance FROM credit_customers WHERE customer_id = %s
            """, (customer_id,))
            
            customer = cur.fetchone()
            if not customer:
                return jsonify({'message': 'Customer not found'}), 404
            
            previous_balance = float(customer['current_balance'])

            # Calculate new balance
            amount = float(data.get('amount'))
            if data.get('transaction_type') == 'credit':
                new_balance = previous_balance + amount
            else:
                new_balance = previous_balance - amount

            # ── Idempotency guard ──────────────────────────────────────────────
            # Reject an identical transaction submitted within a short window
            # (same customer, type, amount, invoice_no, note) — this stops a
            # double-click / retry from inserting duplicate ledger rows and
            # compounding the balance. Returns the existing row instead of a new
            # insert so the client still succeeds. Shared with routes/suppliers.py
            # and the credit-sale auto-post in routes/sales.py via ledger_utils.
            dup = find_recent_duplicate(
                cur, 'credit_transactions', 'customer_id', customer_id,
                data.get('transaction_type'), amount,
                'invoice_no', data.get('invoice_no') or None, data.get('note') or None
            )
            if dup:
                dup['amount'] = float(dup['amount'])
                # The customer's current balance already reflects the first insert;
                # return it as-is (do NOT apply the amount a second time).
                return jsonify({
                    'message': 'Transaction added successfully',
                    'transaction': dup,
                    'new_balance': previous_balance,
                    'duplicate_ignored': True
                }), 200

            # Insert transaction
            cur.execute("""
                INSERT INTO credit_transactions (
                    customer_id, transaction_type, amount, invoice_no, note, previous_balance
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING transaction_id, transaction_type, amount, invoice_no, note, previous_balance, created_at
            """, (
                customer_id,
                data.get('transaction_type'),
                amount,
                data.get('invoice_no') or None,
                data.get('note') or None,
                previous_balance
            ))
            
            transaction = cur.fetchone()
            
            # Update customer's balance
            cur.execute("""
                UPDATE credit_customers
                SET current_balance = %s, updated_at = %s
                WHERE customer_id = %s
            """, (new_balance, datetime.now(), customer_id))
            
            # Commit transaction
            conn.commit()
            
            return jsonify({
                'message': 'Transaction added successfully',
                'transaction': transaction,
                'new_balance': new_balance
            }), 201
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Add credit transaction error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to add transaction', 'error': str(e)}), 500

@credit_bp.route('/search', methods=['GET'])
@token_required
def search_credit_customers(payload):
    """Search credit customers by mobile number (for use in sales)"""
    try:
        mobile = request.args.get('mobile', '')
        
        if not mobile:
            return jsonify({'message': 'Mobile number is required'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Search customers by mobile number - return all matching customers
            # Use contains matching to find all customers whose mobile contains the search term
            # This enables predictive search functionality
            search_pattern = f'%{mobile}%'
            cur.execute("""
                SELECT customer_id, customer_uuid, name, mobile, email, current_balance
                FROM credit_customers
                WHERE mobile LIKE %s
                ORDER BY name
            """, (search_pattern,))
            
            customers = cur.fetchall()
            
            # Ensure current_balance is a float for consistency
            for customer in customers:
                if 'current_balance' in customer and customer['current_balance'] is not None:
                    customer['current_balance'] = float(customer['current_balance'])
            
            return jsonify({
                'customers': customers
            }), 200
            
        except Exception as e:
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Search credit customers error: {str(e)}")
        print(f"Traceback: {error_traceback}")
        return jsonify({'message': 'Failed to search customers', 'error': str(e)}), 500


def _build_credit_csv(customer, transactions):
    """Generate a UTF-8 BOM CSV of a customer's credit history (Excel-compatible)."""
    output = io.StringIO()
    w = csv.writer(output)

    bal = float(customer.get('current_balance') or 0)
    bal_text = f"Rs.{abs(bal):.2f} {'(Credit)' if bal < 0 else '(Debt)' if bal > 0 else ''}"

    w.writerow(['Customer Credit Report'])
    w.writerow(['Generated on', datetime.now().strftime('%d/%m/%Y %H:%M:%S')])
    w.writerow([])
    w.writerow(['Customer ID',   customer.get('customer_uuid', '')])
    w.writerow(['Customer Name', customer.get('name', '')])
    w.writerow(['Mobile',        customer.get('mobile', '')])
    w.writerow(['Email',         customer.get('email') or 'N/A'])
    w.writerow(['Address',       customer.get('address') or 'N/A'])
    w.writerow(['Current Balance', bal_text])
    w.writerow([])

    if not transactions:
        w.writerow(['No transactions found.'])
    else:
        w.writerow(['Date', 'Transaction Type', 'Amount (Rs.)', 'Balance Before', 'Invoice Number', 'Note'])

        # Reverse-calculate the opening balance
        running = bal
        for t in reversed(transactions):
            amt = float(t.get('amount') or 0)
            if t.get('transaction_type') == 'credit':
                running -= amt
            else:
                running += amt

        for t in transactions:
            try:
                ca = t.get('created_at')
                date = ca.strftime('%d/%m/%Y') if hasattr(ca, 'strftime') else str(ca)[:10]
            except Exception:
                date = str(t.get('created_at', ''))[:10]

            amt = float(t.get('amount') or 0)
            txn_type = 'Credit' if t.get('transaction_type') == 'credit' else 'Debit'
            bal_before = f"{running:.2f}"
            invoice_no = t.get('invoice_no') or 'N/A'
            note = t.get('note') or ''

            w.writerow([date, txn_type, f"{amt:.2f}", bal_before, invoice_no, note])

            if t.get('transaction_type') == 'credit':
                running += amt
            else:
                running -= amt

    return output.getvalue().encode('utf-8-sig')  # BOM for Excel


@credit_bp.route('/customers/<int:customer_id>/send-email', methods=['POST'])
@admin_required
def send_credit_email(payload, customer_id):
    """Send a customer's credit statement as a CSV attachment via email."""
    from routes.email_invoice import _send_email

    data = request.get_json() or {}
    to_email = (data.get('email') or '').strip()
    if not to_email or '@' not in to_email:
        return jsonify({'error': 'Valid email address is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT customer_id, customer_code, customer_uuid, name, mobile, email, address, current_balance
            FROM credit_customers WHERE customer_id = %s
        """, (customer_id,))
        customer = cur.fetchone()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        cur.execute("""
            SELECT transaction_id, transaction_type, amount, invoice_no, note, previous_balance, created_at
            FROM credit_transactions
            WHERE customer_id = %s
            ORDER BY created_at ASC
        """, (customer_id,))
        transactions = [dict(r) for r in cur.fetchall()]
        for t in transactions:
            t['amount'] = float(t['amount'] or 0)

        cust_dict = dict(customer)
        cust_dict['current_balance'] = float(cust_dict.get('current_balance') or 0)

        csv_bytes = _build_credit_csv(cust_dict, transactions)
        filename  = f"credit_statement_{cust_dict.get('customer_uuid', customer_id)}.csv"

        bal_val   = cust_dict['current_balance']
        bal_color = '#dc2626' if bal_val > 0 else '#16a34a'
        bal_label = '(Outstanding)' if bal_val > 0 else '(Credit)' if bal_val < 0 else ''
        bal_str   = f'&#8377;{abs(bal_val):.2f} {bal_label}'.strip()

        subject   = f"Credit Statement - {cust_dict['name']}"
        html_body = (
            '<div style="font-family:\'Segoe UI\',Tahoma,sans-serif;font-size:14px;color:#333;max-width:520px;">'
            '<h2 style="color:#4f46e5;margin-bottom:8px;">Credit Statement</h2>'
            f'<p>Dear <strong>{cust_dict["name"]}</strong>,</p>'
            '<p>Please find attached your credit statement as a CSV file.</p>'
            '<table style="border-collapse:collapse;margin:12px 0;width:100%;font-size:13px;">'
            '<tr><td style="padding:4px 8px;font-weight:600;color:#555;">Customer ID</td>'
            f'<td style="padding:4px 8px;">{cust_dict.get("customer_code", "")}</td></tr>'
            '<tr style="background:#f5f5f5;"><td style="padding:4px 8px;font-weight:600;color:#555;">Mobile</td>'
            f'<td style="padding:4px 8px;">{cust_dict.get("mobile", "")}</td></tr>'
            '<tr><td style="padding:4px 8px;font-weight:600;color:#555;">Current Balance</td>'
            f'<td style="padding:4px 8px;font-weight:700;color:{bal_color};">{bal_str}</td></tr>'
            '</table>'
            '<p style="color:#64748b;font-size:12px;">The attached CSV contains your full transaction history.</p>'
            '<p style="margin-top:16px;">Regards,<br><strong>TrintzERP</strong></p>'
            '</div>'
        )

        ok, msg = _send_email(
            to_email, cust_dict['name'], subject, html_body,
            attachments=[{'filename': filename, 'data': csv_bytes, 'mime': 'text/csv'}]
        )
        if ok:
            return jsonify({'success': True, 'message': f'Statement sent to {to_email}'})
        return jsonify({'error': msg}), 502

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)