from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_login_bp = Blueprint('admin_login', __name__)

@admin_login_bp.route('/admin/login-activity', methods=['GET'])
@admin_required
def get_login_activity(payload):
    """Get login activity logs with optional filters"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get filter parameters
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        username = request.args.get('username')
        status = request.args.get('status')
        
        # Build query with filters
        query = """
            SELECT 
                la.id,
                la.user_id,
                la.username,
                la.login_timestamp,
                la.ip_address,
                la.browser,
                la.os,
                la.device_type,
                la.location_city,
                la.location_country,
                la.login_status,
                la.failure_reason,
                u.role as user_role
            FROM login_activity la
            LEFT JOIN users u ON la.user_id = u.user_id
            WHERE 1=1
        """
        params = []
        
        if username:
            query += " AND la.username ILIKE %s"
            params.append(f'%{username}%')
        
        if status:
            query += " AND la.login_status = %s"
            params.append(status)
        
        query += " ORDER BY la.login_timestamp DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        logs = cur.fetchall()
        
        # Get total count for pagination
        count_query = "SELECT COUNT(*) FROM login_activity WHERE 1=1"
        count_params = []
        if username:
            count_query += " AND username ILIKE %s"
            count_params.append(f'%{username}%')
        if status:
            count_query += " AND login_status = %s"
            count_params.append(status)
        
        cur.execute(count_query, count_params)
        total_count = cur.fetchone()['count']
        
        return jsonify({
            'logs': logs,
            'total': total_count,
            'limit': limit,
            'offset': offset
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'message': 'Failed to fetch login activity', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_login_bp.route('/admin/login-activity/stats', methods=['GET'])
@admin_required
def get_login_stats(payload):
    """Get login statistics for dashboard"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Total logins today
        cur.execute("""
            SELECT COUNT(*) as total_today 
            FROM login_activity 
            WHERE login_timestamp >= CURRENT_DATE
        """)
        total_today = cur.fetchone()['total_today']
        
        # Failed logins today
        cur.execute("""
            SELECT COUNT(*) as failed_today 
            FROM login_activity 
            WHERE login_timestamp >= CURRENT_DATE AND login_status = 'failed'
        """)
        failed_today = cur.fetchone()['failed_today']
        
        # Unique users today
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) as unique_users_today 
            FROM login_activity 
            WHERE login_timestamp >= CURRENT_DATE AND user_id IS NOT NULL
        """)
        unique_users = cur.fetchone()['unique_users_today']
        
        # Recent failed login attempts (last 24 hours)
        cur.execute("""
            SELECT username, COUNT(*) as attempts, MAX(login_timestamp) as last_attempt
            FROM login_activity
            WHERE login_status = 'failed' AND login_timestamp >= NOW() - INTERVAL '24 hours'
            GROUP BY username
            ORDER BY attempts DESC
            LIMIT 5
        """)
        failed_attempts = cur.fetchall()
        
        return jsonify({
            'total_today': total_today,
            'failed_today': failed_today,
            'unique_users_today': unique_users,
            'failed_attempts': failed_attempts
        }), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch stats', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_login_bp.route('/admin/login-activity/purge', methods=['DELETE'])
@admin_required
def purge_old_login_activity(payload):
    days = request.args.get('days', 30, type=int)
    if days < 1:
        return jsonify({'error': 'days must be >= 1'}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM login_activity WHERE login_timestamp < NOW() - INTERVAL '%s days'",
            (days,)
        )
        deleted = cur.rowcount
        conn.commit()
        return jsonify({'success': True, 'deleted': deleted, 'message': f'Deleted {deleted} records older than {days} days'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)
