from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required
from psycopg2.extras import RealDictCursor
from ledger_utils import find_recent_duplicate
import re

suppliers_bp = Blueprint('suppliers', __name__)

def validate_gst_number(gst_number):
    """Validate GST number format"""
    if not gst_number:
        return False
    # GST format: 2 digits + 5 uppercase letters + 4 digits + 1 uppercase letter + 1 digit/letter + Z + 1 digit/letter
    gst_pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$'
    return re.match(gst_pattern, gst_number) is not None

def validate_mobile_number(mobile):
    """Validate mobile number format"""
    if not mobile:
        return False
    
    # Clean the mobile number - remove spaces, dashes, parentheses, and country codes
    cleaned_mobile = re.sub(r'[\s\-\(\)\+]', '', mobile)
    
    # Remove leading 0 or country code if present
    if cleaned_mobile.startswith('91') and len(cleaned_mobile) == 12:
        cleaned_mobile = cleaned_mobile[2:]  # Remove India country code
    elif cleaned_mobile.startswith('0') and len(cleaned_mobile) == 11:
        cleaned_mobile = cleaned_mobile[1:]  # Remove leading zero
    
    # Simple mobile validation: 10 digits
    mobile_pattern = r'^[0-9]{10}$'
    return re.match(mobile_pattern, cleaned_mobile) is not None

@suppliers_bp.route('/suppliers', methods=['GET'])
@token_required
def get_suppliers(payload):
    """Get all suppliers with optional search functionality"""
    # Get search query parameter
    search_query = request.args.get('q', '').strip()
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Base query
        query = "SELECT * FROM suppliers"
        params = []
        
        # Add search conditions if query is provided
        if search_query:
            query += """ WHERE supplier_name ILIKE %s 
                         OR supplier_gst_number ILIKE %s 
                         OR mobile ILIKE %s"""
            search_param = f"%{search_query}%"
            params = [search_param, search_param, search_param]
        
        query += " ORDER BY supplier_name"
        
        cur.execute(query, params)
        
        suppliers = cur.fetchall()
        return jsonify(suppliers), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch suppliers', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers', methods=['POST'])
@admin_required
def create_supplier(payload):
    """Create a new supplier"""
    data = request.get_json()
    
    # Validate required fields
    if not data.get('supplier_name'):
        return jsonify({'message': 'Supplier name is required'}), 400
    
    if not data.get('supplier_gst_number'):
        return jsonify({'message': 'GST number is required'}), 400
    
    if not data.get('mobile'):
        return jsonify({'message': 'Mobile number is required'}), 400
    
    # Validate GST number
    if not validate_gst_number(data.get('supplier_gst_number')):
        return jsonify({'message': 'Invalid GST number format'}), 400
    
    # Validate mobile number
    if not validate_mobile_number(data.get('mobile')):
        return jsonify({'message': 'Invalid mobile number format (10 digits required)'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier with same GST number already exists
        cur.execute("""
            SELECT supplier_id FROM suppliers 
            WHERE supplier_gst_number = %s
        """, (data.get('supplier_gst_number'),))
        
        existing_supplier = cur.fetchone()
        if existing_supplier:
            return jsonify({'message': 'Supplier with this GST number already exists'}), 400
        
        # Insert new supplier
        cur.execute("""
            INSERT INTO suppliers (
                supplier_name, supplier_gst_number, contact_person, email, 
                mobile, address, bank_name, bank_account_number, ifsc_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING supplier_id
        """, (
            data.get('supplier_name'),
            data.get('supplier_gst_number'),
            data.get('contact_person'),
            data.get('email'),
            data.get('mobile'),
            data.get('address'),
            data.get('bank_name'),
            data.get('bank_account_number'),
            data.get('ifsc_code')
        ))
        
        supplier = cur.fetchone()
        if not supplier:
            raise Exception('Failed to create supplier')
        
        conn.commit()
        
        # Return the created supplier
        cur.execute("""
            SELECT * FROM suppliers WHERE supplier_id = %s
        """, (supplier['supplier_id'],))
        
        new_supplier = cur.fetchone()
        return jsonify(new_supplier), 201
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error creating supplier: {str(e)}")
        return jsonify({'message': 'Failed to create supplier', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>', methods=['PUT'])
@admin_required
def update_supplier(payload, supplier_id):
    """Update an existing supplier"""
    data = request.get_json()
    
    # Validate GST number if provided
    if data.get('supplier_gst_number') and not validate_gst_number(data.get('supplier_gst_number')):
        return jsonify({'message': 'Invalid GST number format'}), 400
    
    # Validate mobile number if provided
    if data.get('mobile') and not validate_mobile_number(data.get('mobile')):
        return jsonify({'message': 'Invalid mobile number format (10 digits required)'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        existing_supplier = cur.fetchone()
        if not existing_supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Check if another supplier already has this GST number
        if data.get('supplier_gst_number'):
            cur.execute("""
                SELECT supplier_id FROM suppliers 
                WHERE supplier_gst_number = %s AND supplier_id != %s
            """, (data.get('supplier_gst_number'), supplier_id))
            
            duplicate_supplier = cur.fetchone()
            if duplicate_supplier:
                return jsonify({'message': 'Another supplier with this GST number already exists'}), 400
        
        # Update supplier
        update_fields = []
        update_values = []
        
        for field in ['supplier_name', 'supplier_gst_number', 'contact_person', 'email', 
                     'mobile', 'address', 'bank_name', 'bank_account_number', 'ifsc_code']:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])
        
        if not update_fields:
            return jsonify({'message': 'No fields to update'}), 400
        
        update_values.append(supplier_id)
        
        cur.execute(f"""
            UPDATE suppliers 
            SET {', '.join(update_fields)}
            WHERE supplier_id = %s
        """, update_values)
        
        conn.commit()
        
        # Return the updated supplier
        cur.execute("""
            SELECT * FROM suppliers WHERE supplier_id = %s
        """, (supplier_id,))
        
        updated_supplier = cur.fetchone()
        return jsonify(updated_supplier), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'message': 'Failed to update supplier', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>', methods=['DELETE'])
@admin_required
def delete_supplier(payload, supplier_id):
    """Delete a supplier"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        existing_supplier = cur.fetchone()
        if not existing_supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Check if supplier is referenced in purchase orders
        cur.execute("""
            SELECT COUNT(*) as count FROM purchase_orders 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        purchase_count = cur.fetchone()
        if purchase_count and purchase_count['count'] > 0:
            return jsonify({'message': 'Cannot delete supplier with existing purchase orders'}), 400
        
        # Delete supplier
        cur.execute("""
            DELETE FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        if cur.rowcount == 0:
            return jsonify({'message': 'Supplier not found'}), 404
        
        conn.commit()
        return jsonify({'message': 'Supplier deleted successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'message': 'Failed to delete supplier', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>/transactions', methods=['GET'])
@token_required
def get_supplier_transactions(payload, supplier_id):
    """Get all transactions for a supplier"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        supplier = cur.fetchone()
        if not supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Fetch transactions for this supplier
        cur.execute("""
            SELECT * FROM supplier_transactions
            WHERE supplier_id = %s
            ORDER BY created_at DESC
        """, (supplier_id,))
        
        transactions = cur.fetchall()
        return jsonify(transactions or []), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch transactions', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>/transactions/<int:transaction_id>', methods=['GET'])
@token_required
def get_supplier_transaction(payload, supplier_id, transaction_id):
    """Get a specific transaction for a supplier"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        supplier = cur.fetchone()
        if not supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Fetch specific transaction
        cur.execute("""
            SELECT * FROM supplier_transactions
            WHERE transaction_id = %s AND supplier_id = %s
        """, (transaction_id, supplier_id))
        
        transaction = cur.fetchone()
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404
        
        return jsonify(transaction), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch transaction', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>/transactions', methods=['POST'])
@admin_required
def add_supplier_transaction(payload, supplier_id):
    """Add a transaction for a supplier (for credit purchases)"""
    data = request.get_json()
    
    # Validate required fields
    if not data.get('transaction_type') or data.get('amount') is None:
        return jsonify({'message': 'Transaction type and amount are required'}), 400
    
    if data.get('transaction_type') not in ['credit', 'debit']:
        return jsonify({'message': 'Transaction type must be either credit or debit'}), 400
    
    if float(data.get('amount', 0)) <= 0:
        return jsonify({'message': 'Amount must be greater than 0'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id, current_balance FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        supplier = cur.fetchone()
        if not supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Handle NULL current_balance - set to 0 if NULL
        previous_balance = float(supplier.get('current_balance') or 0)
        if previous_balance is None:
            previous_balance = 0.0
        
        # Calculate new balance
        amount = float(data.get('amount'))
        if data.get('transaction_type') == 'credit':
            # Credit means we owe the supplier
            new_balance = previous_balance + amount
        else:
            # Debit means we paid the supplier
            new_balance = previous_balance - amount

        # Effective values that WILL be stored — reuse them in the guard so the
        # duplicate check compares against exactly what gets inserted.
        eff_po   = data.get('purchase_order_number')
        eff_note = data.get('note', 'Purchase transaction')

        # ── Idempotency guard ──────────────────────────────────────────────────
        # Reject an identical transaction submitted within a short window (same
        # supplier, type, amount, PO number, note). Stops a double-click / retry
        # from inserting duplicate rows and compounding the payable balance.
        # Shared with routes/credit.py's guard via ledger_utils.
        dup = find_recent_duplicate(
            cur, 'supplier_transactions', 'supplier_id', supplier_id,
            data.get('transaction_type'), amount,
            'purchase_order_number', eff_po, eff_note
        )
        if dup:
            # Balance already reflects the first insert; don't apply amount again.
            conn.rollback()
            return jsonify({
                'message': 'Transaction added successfully',
                'transaction_id': dup['transaction_id'],
                'new_balance': previous_balance,
                'duplicate_ignored': True
            }), 200

        # Update supplier's balance
        cur.execute("""
            UPDATE suppliers
            SET current_balance = %s
            WHERE supplier_id = %s
        """, (new_balance, supplier_id))

        # Insert transaction record
        cur.execute("""
            INSERT INTO supplier_transactions (
                supplier_id, transaction_type, amount, previous_balance,
                new_balance, purchase_order_number, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING transaction_id
        """, (
            supplier_id,
            data.get('transaction_type'),
            amount,
            previous_balance,
            new_balance,
            eff_po,
            eff_note
        ))
        
        transaction = cur.fetchone()
        conn.commit()
        
        return jsonify({
            'message': 'Transaction added successfully',
            'new_balance': new_balance,
            'transaction_type': data.get('transaction_type'),
            'amount': amount
        }), 201
        
    except Exception as e:
        if conn:
            conn.rollback()
        import traceback
        print(f"Error adding supplier transaction: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'message': 'Failed to add transaction', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@suppliers_bp.route('/suppliers/<int:supplier_id>/transactions/<int:transaction_id>', methods=['PUT'])
@admin_required
def update_supplier_transaction(payload, supplier_id, transaction_id):
    """Update a supplier transaction"""
    data = request.get_json()
    
    # Validate required fields
    if not data.get('transaction_type') or data.get('amount') is None:
        return jsonify({'message': 'Transaction type and amount are required'}), 400
    
    if data.get('transaction_type') not in ['credit', 'debit']:
        return jsonify({'message': 'Transaction type must be either credit or debit'}), 400
    
    if float(data.get('amount', 0)) <= 0:
        return jsonify({'message': 'Amount must be greater than 0'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if supplier exists
        cur.execute("""
            SELECT supplier_id, current_balance FROM suppliers 
            WHERE supplier_id = %s
        """, (supplier_id,))
        
        supplier = cur.fetchone()
        if not supplier:
            return jsonify({'message': 'Supplier not found'}), 404
        
        # Check if transaction exists and belongs to this supplier
        cur.execute("""
            SELECT * FROM supplier_transactions
            WHERE transaction_id = %s AND supplier_id = %s
        """, (transaction_id, supplier_id))
        
        transaction = cur.fetchone()
        if not transaction:
            return jsonify({'message': 'Transaction not found or does not belong to this supplier'}), 404
        
        # Get the original transaction details
        original_amount = float(transaction['amount'])
        original_type = transaction['transaction_type']
        new_amount = float(data.get('amount'))
        new_type = data.get('transaction_type')
        
        # Calculate balance adjustments
        # If type changed, we need to reverse the original and apply the new
        balance_adjustment = 0
        
        if original_type == new_type:
            # Same type, just difference in amount
            if original_type == 'credit':
                balance_adjustment = original_amount - new_amount
            else:  # debit
                balance_adjustment = new_amount - original_amount
        else:
            # Different type, reverse original and apply new
            if original_type == 'credit':
                # Reverse credit (subtract from balance)
                balance_adjustment -= original_amount
            else:  # debit
                # Reverse debit (add to balance)
                balance_adjustment += original_amount
            
            if new_type == 'credit':
                # Apply new credit (add to balance)
                balance_adjustment += new_amount
            else:  # debit
                # Apply new debit (subtract from balance)
                balance_adjustment -= new_amount
        
        # Update supplier's balance
        new_balance = float(supplier['current_balance']) + balance_adjustment
        cur.execute("""
            UPDATE suppliers
            SET current_balance = %s
            WHERE supplier_id = %s
        """, (new_balance, supplier_id))
        
        # Update transaction record
        cur.execute("""
            UPDATE supplier_transactions
            SET transaction_type = %s, amount = %s, new_balance = %s, note = %s
            WHERE transaction_id = %s
        """, (
            new_type,
            new_amount,
            new_balance,
            data.get('note', transaction['note']),
            transaction_id
        ))
        
        conn.commit()
        
        return jsonify({
            'message': 'Transaction updated successfully',
            'new_balance': new_balance,
            'transaction_type': new_type,
            'amount': new_amount
        }), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
        import traceback
        print(f"Error updating supplier transaction: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'message': 'Failed to update transaction', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
