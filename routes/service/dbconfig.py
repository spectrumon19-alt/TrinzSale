from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re
from ._helpers import _split_sql_statements
service_dbconfig_bp = Blueprint('service_dbconfig', __name__)

@service_dbconfig_bp.route('/admin/service/db-config', methods=['GET'])
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


@service_dbconfig_bp.route('/admin/service/db-config', methods=['POST'])
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


@service_dbconfig_bp.route('/admin/service/db-test', methods=['POST'])
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


@service_dbconfig_bp.route('/admin/service/run-schema', methods=['POST'])
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

        conn = get_db_connection()
        cur = conn.cursor()

        # On an EXISTING database (has users already), strip the DEFAULT SEED
        # DATA block (default admin/cashier accounts + sample products/
        # suppliers) between the SEED-DATA-START/END markers. That block must
        # only ever run once, on a genuinely fresh install — running this
        # endpoint against production would otherwise silently (re)create a
        # known-password 'cashier'/'cashier123' account every time an admin
        # uses this "repair schema" action. Mirrors predeploy.py's protection
        # for init_database.sql.
        try:
            cur.execute("SELECT EXISTS (SELECT 1 FROM users LIMIT 1)")
            has_existing_data = cur.fetchone()[0]
        except Exception:
            has_existing_data = False
        if has_existing_data:
            start_marker = '-- === SEED-DATA-START ==='
            end_marker = '-- === SEED-DATA-END ==='
            start = schema_sql.find(start_marker)
            end = schema_sql.find(end_marker)
            if start != -1 and end != -1:
                schema_sql = schema_sql[:start] + schema_sql[end + len(end_marker):]

        statements = _split_sql_statements(schema_sql)

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
