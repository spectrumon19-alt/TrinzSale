from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re
from ._helpers import _is_select_only, _audit_sql
service_sql_bp = Blueprint('service_sql', __name__)

@service_sql_bp.route('/admin/service/execute-sql', methods=['POST'])
@admin_required
def execute_sql_query(payload):
    """Execute a SQL query and return the results"""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({
                'success': False,
                'message': 'Invalid JSON data provided'
            }), 400
            
        query = data.get('query', '')
        confirm_destructive = bool(data.get('confirm_destructive', False))

        if not query or not query.strip():
            return jsonify({
                'success': False,
                'message': 'No query provided'
            }), 400

        select_only = _is_select_only(query)

        # ── Read path: SELECT runs in a server-enforced READ ONLY transaction.
        if select_only:
            try:
                from db import run_readonly_query
                columns, results = run_readonly_query(query, timeout_ms=15000, max_rows=1000)
                _audit_sql(payload, query, True, True, row_count=len(results))
                return jsonify({
                    'success': True,
                    'results': results,
                    'columns': columns,
                    'rowCount': len(results)
                }), 200
            except Exception as e:
                _audit_sql(payload, query, True, False, error_msg=str(e))
                return jsonify({
                    'success': False,
                    'message': f'Error executing query: {str(e)}'
                }), 500

        # ── Write path: destructive query. Require explicit confirmation so a
        #    one-click run can't accidentally mutate/drop data.
        if not confirm_destructive:
            return jsonify({
                'success': False,
                'requires_confirmation': True,
                'message': ('This query modifies the database (it is not a read-only '
                            'SELECT). Re-run with confirmation to proceed.')
            }), 409

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            if conn is None:
                _audit_sql(payload, query, False, False, error_msg='DB connection failed')
                return jsonify({
                    'success': False,
                    'message': 'Database connection failed'
                }), 500

            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SET statement_timeout = 30000")
            cur.execute(query)
            conn.commit()
            affected = cur.rowcount
            _audit_sql(payload, query, False, True, row_count=affected)
            return jsonify({
                'success': True,
                'message': f'Query executed successfully. Rows affected: {affected}'
            }), 200

        except Exception as e:
            if conn:
                conn.rollback()
            _audit_sql(payload, query, False, False, error_msg=str(e))
            return jsonify({
                'success': False,
                'message': f'Error executing query: {str(e)}'
            }), 500
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
                
    except Exception as e:
        # Log the error for debugging
        import traceback
        error_details = f"{str(e)}\n{traceback.format_exc()}"
        print(f"Error in execute_sql_query: {error_details}")
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500

@service_sql_bp.route('/admin/service/execute-sql', methods=['OPTIONS'])
def execute_sql_options():
    """Handle OPTIONS request for execute-sql endpoint"""
    return '', 200

@service_sql_bp.route('/admin/service/clean-test-data', methods=['POST'])
@admin_required
def clean_test_data(payload):
    """Clean all test data while preserving user accounts"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Delete test data in correct order to avoid foreign key constraints
        # Delete sales invoice items first
        cur.execute("DELETE FROM sales_invoice_items")
        
        # Delete sales invoices
        cur.execute("DELETE FROM sales_invoices")
        
        # Delete purchase order items
        cur.execute("DELETE FROM purchase_order_items")
        
        # Delete purchase orders
        cur.execute("DELETE FROM purchase_orders")
        
        # Delete suppliers
        cur.execute("DELETE FROM suppliers")
        
        # Delete inventory
        cur.execute("DELETE FROM inventory")
        
        # Delete products
        cur.execute("DELETE FROM products")
        
        # Reset sequences (PostgreSQL specific)
        try:
            cur.execute("SELECT setval(pg_get_serial_sequence('products', 'product_id'), COALESCE(MAX(product_id), 1)) FROM products")
            cur.execute("SELECT setval(pg_get_serial_sequence('suppliers', 'supplier_id'), COALESCE(MAX(supplier_id), 1)) FROM suppliers")
            cur.execute("SELECT setval(pg_get_serial_sequence('sales_invoices', 'invoice_id'), COALESCE(MAX(invoice_id), 1)) FROM sales_invoices")
            cur.execute("SELECT setval(pg_get_serial_sequence('purchase_orders', 'purchase_order_id'), COALESCE(MAX(purchase_order_id), 1)) FROM purchase_orders")
        except:
            # If sequence reset fails, it's not critical
            pass
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Test data cleaned successfully'
        }), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({
            'success': False,
            'message': f'Error cleaning test data: {str(e)}'
        }), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)


# New endpoints for database configuration
