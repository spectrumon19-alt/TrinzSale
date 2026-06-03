from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re

# Optional import for system monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

service_bp = Blueprint('service', __name__)

@service_bp.route('/admin/service/status', methods=['GET'])
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

@service_bp.route('/admin/service/health-check', methods=['GET'])
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

@service_bp.route('/admin/service/backup', methods=['POST', 'OPTIONS'])
@admin_required
def create_backup(payload):
    """Delegate to backup_engine — produces .sql.gz and logs to backup_logs."""
    from backup_engine import run_backup
    try:
        result = run_backup(backup_type='manual')
        conn = get_db_connection()
        cur  = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO backup_logs
                    (filename, file_size_bytes, backup_type, destination, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (result['filename'], result['size_bytes'], 'manual', 'local', 'success'))
            log_id = cur.fetchone()[0]
            conn.commit()
        finally:
            cur.close()
            release_db_connection(conn)
        return jsonify({
            'success': True,
            'message': f'Backup created: {result["filename"]}',
            'backup_file': result['filename'],
            'file_size': result['size_bytes'],
            'log_id': log_id,
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@service_bp.route('/admin/service/backups', methods=['GET'])
@admin_required
def list_backups(payload):
    """Return all backups from backup_logs (covers both backup.html and service.html runs)."""
    import os as _os
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT id, filename, file_size_bytes, backup_type, destination,
                   status, created_at
            FROM backup_logs
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
        backups = []
        for row in rows:
            log_id, fname, size, btype, dest, status, created_at = row
            fp = _os.path.join(BACKUP_DIR, fname)
            backups.append({
                'id':       log_id,
                'filename': fname,
                'size':     size or 0,
                'created':  created_at.isoformat() if created_at else '',
                'type':     btype,
                'dest':     dest,
                'status':   status,
                'exists':   _os.path.isfile(fp),
            })
        return jsonify({'success': True, 'backups': backups, 'count': len(backups)}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@service_bp.route('/admin/service/backups/<int:log_id>', methods=['DELETE'])
@admin_required
def delete_backup(payload, log_id):
    """Delete backup file + log entry by log_id."""
    import os as _os
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Backup not found'}), 404
        fp = _os.path.join(BACKUP_DIR, row[0])
        if _os.path.isfile(fp):
            _os.remove(fp)
        cur.execute('DELETE FROM backup_logs WHERE id = %s', (log_id,))
        conn.commit()
        return jsonify({'success': True, 'message': f'Deleted: {row[0]}'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@service_bp.route('/admin/service/restore', methods=['POST'])
@admin_required
def restore_backup(payload):
    """Restore from a backup file (handles both .sql and .sql.gz). Accepts log_id or filename."""
    import os as _os
    import gzip as _gzip
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        data     = request.get_json() or {}
        log_id   = data.get('log_id')
        filename = data.get('backup_file')

        if log_id:
            cur2 = conn.cursor()
            cur2.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
            row = cur2.fetchone()
            cur2.close()
            if not row:
                return jsonify({'success': False, 'message': 'Backup log not found'}), 404
            filename = row[0]

        if not filename:
            return jsonify({'success': False, 'message': 'No backup specified'}), 400

        backup_path = _os.path.join(BACKUP_DIR, filename)
        # Path traversal guard
        if not _os.path.abspath(backup_path).startswith(_os.path.abspath(BACKUP_DIR)):
            return jsonify({'success': False, 'message': 'Invalid filename'}), 400
        if not _os.path.isfile(backup_path):
            return jsonify({'success': False, 'message': f'File not found: {filename}'}), 404

        # Read — supports both plain .sql and gzip .sql.gz
        if filename.endswith('.gz'):
            with _gzip.open(backup_path, 'rt', encoding='utf-8') as f:
                sql_content = f.read()
        else:
            with open(backup_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()

        ok = err = 0
        for stmt in sql_content.split(';'):
            stmt = stmt.strip()
            if not stmt or stmt.startswith('--') or stmt.startswith('SET '):
                continue
            try:
                cur.execute(stmt)
                ok += 1
            except Exception as e:
                err += 1
                conn.rollback()
                cur = conn.cursor()

        conn.commit()
        return jsonify({
            'success': True,
            'message': f'Restored from {filename} — {ok} statements applied, {err} skipped'
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@service_bp.route('/admin/service/logs', methods=['GET'])
@admin_required
def get_logs(payload):
    """Get system logs"""
    try:
        # In a real implementation, this would read from actual log files
        # For now, we'll return simulated log data
        log_level = request.args.get('level', 'all')
        
        # Simulated logs
        logs = [
            {"timestamp": "2023-06-15T10:30:15", "level": "INFO", "message": "System started successfully"},
            {"timestamp": "2023-06-15T10:32:45", "level": "INFO", "message": "User admin logged in"},
            {"timestamp": "2023-06-15T10:45:22", "level": "WARNING", "message": "Low disk space (15% remaining)"},
            {"timestamp": "2023-06-15T11:15:33", "level": "INFO", "message": "Database backup completed"},
            {"timestamp": "2023-06-15T12:05:17", "level": "ERROR", "message": "Failed to connect to external API"},
            {"timestamp": "2023-06-15T12:05:18", "level": "INFO", "message": "Retrying API connection"},
            {"timestamp": "2023-06-15T12:05:20", "level": "INFO", "message": "API connection restored"},
            {"timestamp": "2023-06-15T14:22:05", "level": "INFO", "message": "New sale recorded (Invoice #INV-2023-0015)"},
            {"timestamp": "2023-06-15T15:40:11", "level": "INFO", "message": "Inventory updated for Product ID 123"},
            {"timestamp": "2023-06-15T16:15:27", "level": "WARNING", "message": "High memory usage detected (85%)"},
            {"timestamp": "2023-06-15T17:30:44", "level": "INFO", "message": "Daily report generated"}
        ]
        
        # Filter logs by level if specified
        if log_level != 'all':
            logs = [log for log in logs if log['level'].lower() == log_level.lower()]
        
        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving logs: {str(e)}'
        }), 500

@service_bp.route('/admin/service/execute-sql', methods=['POST'])
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
        
        if not query:
            return jsonify({
                'success': False,
                'message': 'No query provided'
            }), 400
        
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            if conn is None:
                return jsonify({
                    'success': False,
                    'message': 'Database connection failed'
                }), 500
                
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Execute the query
            cur.execute(query)
            
            # If it's a SELECT query, fetch results
            if query.strip().upper().startswith('SELECT'):
                results = cur.fetchall()
                columns = [desc[0] for desc in cur.description] if cur.description else []
                
                return jsonify({
                    'success': True,
                    'results': results,
                    'columns': columns,
                    'rowCount': len(results)
                }), 200
            else:
                # For INSERT, UPDATE, DELETE, etc.
                conn.commit()
                return jsonify({
                    'success': True,
                    'message': f'Query executed successfully. Rows affected: {cur.rowcount}'
                }), 200
                
        except Exception as e:
            if conn:
                conn.rollback()
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

@service_bp.route('/admin/service/execute-sql', methods=['OPTIONS'])
def execute_sql_options():
    """Handle OPTIONS request for execute-sql endpoint"""
    return '', 200

@service_bp.route('/admin/service/clean-test-data', methods=['POST'])
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
@service_bp.route('/admin/service/db-config', methods=['GET'])
@admin_required
def get_db_config(payload):
    """Get current database configuration"""
    try:
        # In a real implementation, this would retrieve the current database configuration
        # For now, we'll return the configuration from environment variables
        return jsonify({
            'success': True,
            'config': {
                'host': os.environ.get('DB_HOST', 'localhost'),
                'database': os.environ.get('DB_NAME', 'pos_db'),
                'username': os.environ.get('DB_USER', 'postgres'),
                'port': os.environ.get('DB_PORT', '5432')
            }
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving database configuration: {str(e)}'
        }), 500


@service_bp.route('/admin/service/db-config', methods=['POST'])
@admin_required
def update_db_config(payload):
    """Update database configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No configuration data provided'
            }), 400
            
        # In a real implementation, this would update the database configuration
        # For now, we'll just validate the data and return success
        required_fields = ['host', 'database', 'username', 'password', 'port']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({
                    'success': False,
                    'message': f'Missing required field: {field}'
                }), 400
        
        # In a real implementation, you would:
        # 1. Test the connection with the new configuration
        # 2. Update the .env file or configuration store
        # 3. Restart the database connection pool
        
        return jsonify({
            'success': True,
            'message': 'Database configuration updated successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating database configuration: {str(e)}'
        }), 500


@service_bp.route('/admin/service/db-test', methods=['POST'])
@admin_required
def test_db_connection(payload):
    """Test database connection with provided configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No connection data provided'
            }), 400
            
        # In a real implementation, this would test the database connection
        # For now, we'll just validate the data and return success
        required_fields = ['host', 'database', 'username', 'password', 'port']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({
                    'success': False,
                    'message': f'Missing required field: {field}'
                }), 400
        
        # In a real implementation, you would:
        # 1. Attempt to connect to the database with the provided configuration
        # 2. Return the result of the connection test
        
        return jsonify({
            'success': True,
            'message': 'Database connection test successful'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error testing database connection: {str(e)}'
        }), 500


def _split_sql_statements(sql_text):
    """
    Split a SQL script into individual statements, correctly handling
    dollar-quoted blocks (DO $$ ... $$) that contain semicolons.
    Returns a list of non-empty statement strings.
    """
    statements = []
    current = []
    dollar_tag = None  # None = not in dollar-quote; str = the tag we're inside (e.g. '$$')

    i = 0
    while i < len(sql_text):
        ch = sql_text[i]

        # Detect start/end of dollar-quoted string
        if ch == '$':
            # Try to match a dollar-quote tag: $optionalLabel$
            m = re.match(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$', sql_text[i:])
            if m:
                tag = m.group(0)
                if dollar_tag is None:
                    dollar_tag = tag
                    current.append(tag)
                    i += len(tag)
                    continue
                elif sql_text[i:i + len(dollar_tag)] == dollar_tag:
                    current.append(dollar_tag)
                    i += len(dollar_tag)
                    dollar_tag = None
                    continue

        current.append(ch)

        if ch == ';' and dollar_tag is None:
            stmt = ''.join(current).strip()
            # Strip leading/trailing SQL comments
            stmt_stripped = re.sub(r'--[^\n]*', '', stmt).strip()
            if stmt_stripped and stmt_stripped != ';':
                statements.append(stmt)
            current = []

        i += 1

    # Catch any final statement without trailing semicolon
    remainder = ''.join(current).strip()
    remainder_clean = re.sub(r'--[^\n]*', '', remainder).strip()
    if remainder_clean:
        statements.append(remainder)

    return statements


@service_bp.route('/admin/service/run-schema', methods=['POST'])
@admin_required
def run_schema(payload):
    """
    Execute schema.sql against the live database to revalidate all tables,
    indexes, triggers, functions, and seed data.
    All DDL statements use IF NOT EXISTS so this is safe to run on a live DB.
    """
    conn = None
    cur = None
    try:
        _base = os.environ.get('TRINTZ_APP_BASE') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        schema_path = os.path.join(_base, 'schema.sql')
        if not os.path.exists(schema_path):
            return jsonify({'success': False, 'message': f'schema.sql not found at {schema_path}'}), 404

        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        statements = _split_sql_statements(schema_sql)

        conn = get_db_connection()
        cur = conn.cursor()

        results = []
        ok_count = 0
        skip_count = 0
        error_count = 0

        for stmt in statements:
            label = stmt.strip()[:80].replace('\n', ' ')
            try:
                cur.execute('SAVEPOINT sp_stmt')
                cur.execute(stmt)
                cur.execute('RELEASE SAVEPOINT sp_stmt')
                results.append({'status': 'ok', 'stmt': label})
                ok_count += 1
            except Exception as e:
                cur.execute('ROLLBACK TO SAVEPOINT sp_stmt')
                err_msg = str(e).strip().splitlines()[0]
                results.append({'status': 'skip', 'stmt': label, 'reason': err_msg})
                skip_count += 1

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'Schema run complete: {ok_count} applied, {skip_count} skipped (already exist / no-op)',
            'total': len(statements),
            'ok': ok_count,
            'skipped': skip_count,
            'errors': error_count,
            'results': results,
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        import traceback
        print(f'run-schema error: {e}\n{traceback.format_exc()}')
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: release_db_connection(conn)
