from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re
from ._helpers import PSUTIL_AVAILABLE
service_status_bp = Blueprint('service_status', __name__)

@service_status_bp.route('/admin/service/status', methods=['GET'])
@admin_required
def get_service_status(payload):
    """Get system status and record counts"""
    print("Service status endpoint called")
    conn = None
    cur = None
    try:
        print("Attempting database connection")
        conn = get_db_connection()
        print("Database connection successful")
        cur = conn.cursor(cursor_factory=RealDictCursor)
        print("Cursor created successfully")
        
        # Get record counts
        record_counts = {}
        print("Fetching record counts...")
        
        # Count products
        cur.execute("SELECT COUNT(*) as count FROM products")
        result = cur.fetchone()
        record_counts['products'] = result['count'] if result else 0
        print(f"Products count: {record_counts['products']}")
        
        # Count suppliers
        cur.execute("SELECT COUNT(*) as count FROM suppliers")
        result = cur.fetchone()
        record_counts['suppliers'] = result['count'] if result else 0
        print(f"Suppliers count: {record_counts['suppliers']}")
        
        # Count sales invoices
        cur.execute("SELECT COUNT(*) as count FROM sales_invoices")
        result = cur.fetchone()
        record_counts['sales_invoices'] = result['count'] if result else 0
        print(f"Sales invoices count: {record_counts['sales_invoices']}")
        
        # Count purchase orders
        cur.execute("SELECT COUNT(*) as count FROM purchase_orders")
        result = cur.fetchone()
        record_counts['purchase_orders'] = result['count'] if result else 0
        print(f"Purchase orders count: {record_counts['purchase_orders']}")
        
        # Count users
        cur.execute("SELECT COUNT(*) as count FROM users")
        result = cur.fetchone()
        record_counts['users'] = result['count'] if result else 0
        print(f"Users count: {record_counts['users']}")
        
        # Count inventory items
        cur.execute("SELECT COUNT(*) as count FROM inventory")
        result = cur.fetchone()
        record_counts['inventory_items'] = result['count'] if result else 0
        print(f"Inventory items count: {record_counts['inventory_items']}")
        
        print("All counts fetched successfully")
        return jsonify({
            'status': 'Connected',
            'recordCounts': record_counts
        }), 200
        
    except Exception as e:
        print(f"Error in service status endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'Error',
            'message': str(e)
        }), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)

@service_status_bp.route('/admin/service/health-check', methods=['GET'])
@admin_required
def health_check(payload):
    """Perform a comprehensive system health check"""
    try:
        # Database health check
        db_status = {"status": "OK"}
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
        except Exception as e:
            db_status = {"status": "ERROR", "message": str(e)}
        finally:
            if cur:
                cur.close()
            if conn:
                release_db_connection(conn)
        
        # Disk space check
        disk_status = {"status": "OK"}
        if PSUTIL_AVAILABLE:
            try:
                # Use appropriate disk path based on OS
                if platform.system() == "Windows":
                    # On Windows, use the system drive (usually C:)
                    disk_usage = psutil.disk_usage('C:\\')
                else:
                    # On Unix-like systems, use root
                    disk_usage = psutil.disk_usage('/')
                    
                disk_percent = (disk_usage.used / disk_usage.total) * 100
                disk_message = f"{disk_percent:.1f}% used ({disk_usage.free / (1024**3):.1f} GB free)"
                
                if disk_percent > 90:
                    disk_status = {"status": "ERROR", "message": disk_message}
                elif disk_percent > 80:
                    disk_status = {"status": "WARNING", "message": disk_message}
                else:
                    disk_status = {"status": "OK", "message": disk_message}
            except Exception as e:
                disk_status = {"status": "ERROR", "message": f"Unable to check disk space: {str(e)}"}
        else:
            # Fallback when psutil is not available
            disk_status = {"status": "INFO", "message": "Disk space monitoring not available"}
        
        # Memory usage check
        memory_status = {"status": "OK"}
        if PSUTIL_AVAILABLE:
            try:
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                memory_message = f"{memory_percent:.1f}% used ({memory.available / (1024**3):.1f} GB free)"

                if memory_percent > 90:
                    memory_status = {"status": "ERROR", "message": memory_message}
                elif memory_percent > 80:
                    memory_status = {"status": "WARNING", "message": memory_message}
                else:
                    memory_status = {"status": "OK", "message": memory_message}
            except Exception as e:
                memory_status = {"status": "ERROR", "message": f"Unable to check memory: {str(e)}"}
        else:
            memory_status = {"status": "INFO", "message": "Memory monitoring not available (psutil not installed)"}

        # Required database tables check
        tables_status = {"status": "INFO", "message": "Skipped (DB not connected)"}
        if db_status["status"] == "OK":
            try:
                conn2 = get_db_connection()
                cur2 = conn2.cursor()
                cur2.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                existing = {row[0] for row in cur2.fetchall()}
                cur2.close()
                release_db_connection(conn2)
                required = [
                    'users', 'products', 'suppliers', 'sales_invoices', 'sales_invoice_items',
                    'purchase_orders', 'purchase_order_items', 'inventory', 'permissions',
                    'registration_otps', 'login_otps', 'trusted_devices', 'password_reset_otps',
                ]
                missing = [t for t in required if t not in existing]
                if missing:
                    tables_status = {"status": "WARNING", "message": f"Missing tables: {', '.join(missing)}"}
                else:
                    tables_status = {"status": "OK", "message": f"All {len(required)} required tables present"}
            except Exception as e:
                tables_status = {"status": "ERROR", "message": f"Table check failed: {str(e)}"}

        # Environment variables check
        required_env = ['SECRET_KEY']
        db_env = ['DATABASE_URL', 'DB_HOST']
        email_env = ['BREVO_API_KEY', 'BREVO_SENDER_EMAIL']
        missing_required = [e for e in required_env if not os.environ.get(e)]
        has_db = any(os.environ.get(e) for e in db_env)
        has_email = all(os.environ.get(e) for e in email_env)
        if missing_required:
            env_status = {"status": "ERROR", "message": f"Missing required vars: {', '.join(missing_required)}"}
        elif not has_db:
            env_status = {"status": "WARNING", "message": "No DATABASE_URL or DB_HOST set"}
        elif not has_email:
            env_status = {"status": "WARNING", "message": "Email not configured (BREVO_API_KEY / BREVO_SENDER_EMAIL missing)"}
        else:
            env_status = {"status": "OK", "message": "All required environment variables are set"}

        return jsonify({
            "database":    db_status,
            "disk":        disk_status,
            "memory":      memory_status,
            "tables":      tables_status,
            "environment": env_status,
            "timestamp":   datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        # Ensure we always return JSON even if there's an error
        return jsonify({
            "error": f"Health check failed: {str(e)}"
        }), 500
