from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_invoices_bp = Blueprint('admin_invoices', __name__)

@admin_invoices_bp.route('/admin/invoices', methods=['GET', 'HEAD'])
@permission_required('invoice-viewer')
def get_all_invoices(payload):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT
                si.invoice_id,
                si.invoice_number,
                si.invoice_date,
                si.customer_name,
                si.total_amount,
                si.total_gst,
                si.status,
                u.username as created_by
            FROM sales_invoices si
            JOIN users u ON si.user_id = u.user_id
            ORDER BY si.invoice_date DESC
        """)
        
        invoices = cur.fetchall()
        return jsonify(invoices), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch invoices', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_invoices_bp.route('/admin/invoices/<int:invoice_id>', methods=['DELETE'])
@admin_required
def delete_invoice(payload, invoice_id):
    """Delete an invoice and add quantities back to inventory"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if invoice exists and get its items
        cur.execute("""
            SELECT si.status, sii.product_id, sii.quantity
            FROM sales_invoices si
            LEFT JOIN sales_invoice_items sii ON si.invoice_id = sii.invoice_id
            WHERE si.invoice_id = %s
        """, (invoice_id,))
        
        rows = cur.fetchall()
        
        if not rows or not rows[0]['status']:
            return jsonify({'message': 'Invoice not found'}), 404
        
        # Check if invoice is already cancelled
        if rows[0]['status'] == 'Cancelled':
            return jsonify({'message': 'Invoice is already cancelled and cannot be deleted'}), 400
        
        # Get all items in the invoice
        items = [row for row in rows if row['product_id'] is not None]
        
        # Update inventory (add quantities back for each item)
        for item in items:
            if item['product_id'] and item['quantity']:
                cur.execute("""
                    UPDATE inventory 
                    SET stock_quantity = stock_quantity + %s 
                    WHERE product_id = %s
                """, (item['quantity'], item['product_id']))
                
                # Check if update was successful
                if cur.rowcount == 0:
                    # If product doesn't exist in inventory, create entry
                    cur.execute("""
                        INSERT INTO inventory (product_id, stock_quantity)
                        VALUES (%s, %s)
                    """, (item['product_id'], item['quantity']))
        
        # Delete invoice items first (due to foreign key constraints)
        cur.execute("DELETE FROM sales_invoice_items WHERE invoice_id = %s", (invoice_id,))
        
        # Delete the invoice
        cur.execute("DELETE FROM sales_invoices WHERE invoice_id = %s", (invoice_id,))
        
        # Commit transaction
        conn.commit()
        
        return jsonify({'message': 'Invoice deleted successfully and quantities added back to inventory'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'message': 'Failed to delete invoice', 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)
