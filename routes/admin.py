from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/users', methods=['GET'])
@admin_required
def get_users(payload):
    import traceback
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT user_id, username, role, full_name, email, mobile,
                   COALESCE(totp_enabled,  FALSE) AS totp_enabled,
                   COALESCE(totp_required, FALSE) AS totp_required,
                   created_at
            FROM users
            ORDER BY created_at DESC
        """)
        
        users = cur.fetchall()
        return jsonify(users), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'message': 'Failed to fetch users', 'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)

@admin_bp.route('/admin/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user(payload, user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT user_id, username, role, full_name, email, mobile, created_at 
            FROM users WHERE user_id = %s
        """, (user_id,))
        
        user = cur.fetchone()
        if not user:
            return jsonify({'message': 'User not found'}), 404
        return jsonify(user), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch user', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/users', methods=['POST'])
@admin_required
def create_user(payload):
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role')
    full_name = data.get('full_name', '')
    email = data.get('email', '')
    mobile = data.get('mobile', '')
    
    if not username or not password or not role:
        return jsonify({'message': 'Username, password, and role are required'}), 400
    if not email or '@' not in email:
        return jsonify({'message': 'A valid email address is required'}), 400
    
    VALID_ROLES = ['Admin', 'Cashier', 'Super Admin', 'Manager']
    if role not in VALID_ROLES:
        return jsonify({'message': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Hash the password
        hashed_password = hash_password(password)
        
        cur.execute("""
            INSERT INTO users (username, password_hash, role, full_name, email, mobile)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (username, hashed_password, role, full_name, email, mobile))
        
        conn.commit()
        return jsonify({'message': 'User created successfully'}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to create user', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/users/<int:user_id>/reset-password', methods=['PUT'])
@admin_required
def reset_user_password(payload, user_id):
    data = request.get_json()
    new_password = data.get('new_password')
    
    if not new_password:
        return jsonify({'message': 'New password is required'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Hash the new password
        hashed_password = hash_password(new_password)
        
        cur.execute("""
            UPDATE users 
            SET password_hash = %s 
            WHERE user_id = %s
        """, (hashed_password, user_id))
        
        if cur.rowcount == 0:
            return jsonify({'message': 'User not found'}), 404
            
        conn.commit()
        return jsonify({'message': 'Password reset successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to reset password', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(payload, user_id):
    data = request.get_json()
    username = data.get('username')
    role = data.get('role')
    password = data.get('password')  # Optional: only update if provided
    full_name = data.get('full_name', '')
    email = data.get('email', '')
    mobile = data.get('mobile', '')
    
    if not username or not role:
        return jsonify({'message': 'Username and role are required'}), 400
    
    VALID_ROLES = ['Admin', 'Cashier', 'Super Admin', 'Manager']
    if role not in VALID_ROLES:
        return jsonify({'message': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # If password is provided, hash it and include in update
        if password:
            hashed_password = hash_password(password)
            cur.execute("""
                UPDATE users 
                SET username = %s, role = %s, password_hash = %s, full_name = %s, email = %s, mobile = %s
                WHERE user_id = %s
            """, (username, role, hashed_password, full_name, email, mobile, user_id))
        else:
            cur.execute("""
                UPDATE users 
                SET username = %s, role = %s, full_name = %s, email = %s, mobile = %s
                WHERE user_id = %s
            """, (username, role, full_name, email, mobile, user_id))
        
        if cur.rowcount == 0:
            return jsonify({'message': 'User not found'}), 404
            
        conn.commit()
        return jsonify({'message': 'User updated successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to update user', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/users/<int:user_id>/delete-preview', methods=['GET'])
@admin_required
def delete_user_preview(payload, user_id):
    """Return a summary of records that will be affected by deleting this user."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, username, full_name, role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'message': 'User not found'}), 404

        cur.execute("SELECT COUNT(*) FROM sales_invoices  WHERE user_id = %s", (user_id,))
        invoices = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM purchase_orders WHERE user_id = %s", (user_id,))
        purchases = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sales_returns   WHERE user_id = %s", (user_id,))
        returns = cur.fetchone()[0]

        # Last-admin guard
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin'")
        admin_count = cur.fetchone()[0]
        is_last_admin = (user[3] == 'Admin' and admin_count <= 1)

        return jsonify({
            'user_id':       user[0],
            'username':      user[1],
            'full_name':     user[2] or user[1],
            'role':          user[3],
            'is_last_admin': is_last_admin,
            'linked': {
                'invoices':  invoices,
                'purchases': purchases,
                'returns':   returns,
            }
        })
    except Exception as e:
        return jsonify({'message': 'Preview failed', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@admin_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(payload, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Check if user exists
        cur.execute("SELECT user_id, username, role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        # Prevent deletion of the last admin user
        cur.execute("SELECT COUNT(*) as admin_count FROM users WHERE role = 'Admin'")
        result = cur.fetchone()
        admin_count = result[0] if result else 0
        
        user_role = user[2] if user else None
        
        if user_role == 'Admin' and admin_count <= 1:
            return jsonify({'message': 'Cannot delete the last admin user'}), 400
        
        # Unlink user from historical records (preserve the records, just remove the FK)
        cur.execute("UPDATE purchase_orders SET user_id = NULL WHERE user_id = %s", (user_id,))
        cur.execute("UPDATE sales_invoices  SET user_id = NULL WHERE user_id = %s", (user_id,))
        cur.execute("UPDATE sales_returns   SET user_id = NULL WHERE user_id = %s", (user_id,))

        # Delete cascading rows (user_permissions, login_otps, trusted_devices, pw_reset_otps)
        cur.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))

        # Delete the user
        cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        
        return jsonify({'message': 'User deleted successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to delete user', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/users/<int:user_id>/totp-required', methods=['PUT'])
@admin_required
def toggle_totp_required(payload, user_id):
    """Admin: enforce or remove TOTP requirement for a specific user."""
    data     = request.get_json() or {}
    required = bool(data.get('required', False))
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not cur.fetchone():
            return jsonify({'message': 'User not found'}), 404
        cur.execute("UPDATE users SET totp_required = %s WHERE user_id = %s", (required, user_id))
        conn.commit()
        status = 'enforced' if required else 'removed'
        return jsonify({'message': f'Authenticator requirement {status}.'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to update', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@admin_bp.route('/admin/invoices', methods=['GET', 'HEAD'])
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

@admin_bp.route('/admin/invoices/<int:invoice_id>', methods=['DELETE'])
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

# Service routes moved to service.py to avoid duplication

# ============================================================
# LOGIN ACTIVITY ENDPOINTS
# ============================================================

@admin_bp.route('/admin/login-activity', methods=['GET'])
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

@admin_bp.route('/admin/login-activity/stats', methods=['GET'])
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

@admin_bp.route('/admin/login-activity/purge', methods=['DELETE'])
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

# ============================================================
# PERMISSIONS ENDPOINTS
# ============================================================

# All screens that can be permission-controlled
PERMISSION_SCREENS = [
    {'id': 'dashboard',           'name': 'Dashboard',           'icon': 'fa-home'},
    {'id': 'sales',               'name': 'Sales',               'icon': 'fa-shopping-cart'},
    {'id': 'returns',             'name': 'Returns & Refunds',   'icon': 'fa-undo'},
    {'id': 'purchase',            'name': 'Purchase',            'icon': 'fa-download'},
    {'id': 'inventory',           'name': 'Inventory',           'icon': 'fa-box'},
    {'id': 'reports',             'name': 'Reports',             'icon': 'fa-chart-bar'},
    {'id': 'admin',               'name': 'Admin Panel',         'icon': 'fa-cog'},
    {'id': 'service',             'name': 'Service',             'icon': 'fa-wrench'},
    {'id': 'credit',              'name': 'Credit Management',   'icon': 'fa-credit-card'},
    {'id': 'data-upload',         'name': 'Data Upload',         'icon': 'fa-upload'},
    {'id': 'qry2db',              'name': 'Query to DB',         'icon': 'fa-database'},
    {'id': 'supplier-management', 'name': 'Supplier Management', 'icon': 'fa-truck'},
    {'id': 'product-management',  'name': 'Product Management',  'icon': 'fa-cubes'},
    {'id': 'user-management',     'name': 'User Management',     'icon': 'fa-users'},
    {'id': 'invoice-viewer',      'name': 'Invoice Viewer',      'icon': 'fa-file-invoice'},
    {'id': 'gst-reports',         'name': 'GST Reports',         'icon': 'fa-file-invoice-dollar'},
    {'id': 'ai-settings',         'name': 'AI Settings',         'icon': 'fa-robot'},
    {'id': 'ocr-excel',           'name': 'OCR → Excel',         'icon': 'fa-file-excel'},
    {'id': 'ai-chat',             'name': 'AI Reports / Chat',   'icon': 'fa-comments'},
    {'id': 'backup',              'name': 'Auto Backup',         'icon': 'fa-shield-alt'},
    {'id': 'tally-export',        'name': 'Tally Export',        'icon': 'fa-file-export'},
    {'id': 'login-activity',      'name': 'Login Activity',      'icon': 'fa-sign-in-alt'},
    {'id': 'store-settings',      'name': 'Store Settings',      'icon': 'fa-store'},
]

@admin_bp.route('/admin/permissions/screens', methods=['GET'])
@admin_required
def get_permission_screens(payload):
    """Get the list of all screens that can be permission-controlled"""
    return jsonify(PERMISSION_SCREENS), 200

@admin_bp.route('/admin/permissions', methods=['GET'])
@admin_required
def get_all_permissions(payload):
    """Get permissions for all users"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get all users (except their passwords)
        cur.execute("""
            SELECT user_id, username, role, full_name FROM users ORDER BY user_id
        """)
        users = cur.fetchall()
        
        # Get all permissions
        cur.execute("""
            SELECT user_id, page_id, has_access FROM user_permissions
        """)
        permissions = cur.fetchall()
        
        # Build a map: user_id -> { page_id: has_access }
        perm_map = {}
        for p in permissions:
            uid = p['user_id']
            if uid not in perm_map:
                perm_map[uid] = {}
            perm_map[uid][p['page_id']] = p['has_access']
        
        # Combine users with their permissions
        result = []
        for user in users:
            result.append({
                'user_id': user['user_id'],
                'username': user['username'],
                'role': user['role'],
                'full_name': user.get('full_name', ''),
                'permissions': perm_map.get(user['user_id'], {})
            })
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch permissions', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/permissions/<int:user_id>', methods=['GET'])
@token_required
def get_user_permissions(payload, user_id):
    """Get permissions for a specific user.
    Admins can view any user's permissions.
    Non-admin users can only view their own permissions."""
    # Non-admin users can only view their own permissions
    if payload.get('role') not in ('Admin', 'Super Admin', 'Manager') and payload.get('user_id') != user_id:
        return jsonify({'message': 'Access denied'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Verify user exists
        cur.execute("SELECT user_id, username, role, full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        # Get user's permissions
        cur.execute("""
            SELECT page_id, has_access FROM user_permissions WHERE user_id = %s
        """, (user_id,))
        perms = cur.fetchall()
        
        permissions = {p['page_id']: p['has_access'] for p in perms}
        
        return jsonify({
            'user_id': user['user_id'],
            'username': user['username'],
            'role': user['role'],
            'full_name': user.get('full_name', ''),
            'permissions': permissions
        }), 200
    except Exception as e:
        return jsonify({'message': 'Failed to fetch user permissions', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/permissions/<int:user_id>', methods=['PUT'])
@admin_required
def update_user_permissions(payload, user_id):
    """Update permissions for a specific user — Super Admin only."""
    if payload.get('role') != 'Super Admin':
        return jsonify({'message': 'Only Super Admin can modify permissions'}), 403
    data = request.get_json()
    permissions = data.get('permissions', {})
    
    if not permissions:
        return jsonify({'message': 'No permissions provided'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Verify user exists
        cur.execute("SELECT user_id, role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        # Don't allow restricting admin's own admin access
        if user[1] == 'Admin' and payload.get('user_id') == user_id:
            if permissions.get('admin') == False:
                return jsonify({'message': 'Cannot remove your own admin access'}), 400
        
        # Upsert each permission
        for page_id, has_access in permissions.items():
            cur.execute("""
                INSERT INTO user_permissions (user_id, page_id, has_access, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, page_id) 
                DO UPDATE SET has_access = %s, updated_at = CURRENT_TIMESTAMP
            """, (user_id, page_id, has_access, has_access))
        
        conn.commit()
        return jsonify({'message': 'Permissions updated successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': 'Failed to update permissions', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)

@admin_bp.route('/admin/permissions/<int:user_id>/check', methods=['GET'])
@token_required
def check_user_permission(payload, user_id):
    """Check if a user has access to a specific screen.
    Admins always have access. For others, check user_permissions table."""
    screen = request.args.get('screen')
    if not screen:
        return jsonify({'message': 'Screen parameter is required'}), 400
    
    # Admins always have access
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'has_access': False}), 200
        
        if user['role'] == 'Admin':
            return jsonify({'has_access': True}), 200
        
        cur.execute("""
            SELECT has_access FROM user_permissions 
            WHERE user_id = %s AND page_id = %s
        """, (user_id, screen))
        perm = cur.fetchone()
        
        # If no record exists, default to accessible
        has_access = perm['has_access'] if perm else True
        return jsonify({'has_access': has_access}), 200
    except Exception as e:
        return jsonify({'has_access': True, 'error': str(e)}), 200
    finally:
        cur.close()
        release_db_connection(conn)


# ── Store Settings ─────────────────────────────────────────────────────────────

ALLOWED_KEYS = {
    'store_name', 'store_address', 'store_phone', 'store_gst',
    'upi_id', 'upi_display_name',
}

_STORE_SETTINGS_DDL = """
CREATE TABLE IF NOT EXISTS store_settings (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT         NOT NULL DEFAULT '',
    updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO store_settings (key, value) VALUES
    ('store_name',        'Nandi Agro'),
    ('store_address',     '#2454, Agasi Main Road, Kolhar - 586210'),
    ('store_phone',       '8660180378'),
    ('store_gst',         '29AASFN9214H1ZP'),
    ('upi_id',            ''),
    ('upi_display_name',  'Nandi Agro')
ON CONFLICT (key) DO NOTHING;
"""

def _ensure_store_settings_table(conn):
    """Create store_settings table and seed rows if they don't exist yet."""
    with conn.cursor() as c:
        c.execute(_STORE_SETTINGS_DDL)
    conn.commit()


@admin_bp.route('/store-settings', methods=['GET'])
@token_required
def get_store_settings(payload):
    """Return all store settings as a flat key→value dict (any authenticated user)."""
    conn = cur = None
    try:
        conn = get_db_connection()
        _ensure_store_settings_table(conn)
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT key, value FROM store_settings")
        rows = cur.fetchall()
        return jsonify({r['key']: r['value'] for r in rows}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: release_db_connection(conn)


@admin_bp.route('/store-settings', methods=['POST'])
@admin_required
def update_store_settings(payload):
    """Upsert one or more store settings. Body: {key: value, ...}"""
    data = request.get_json(force=True) or {}
    updates = {k: str(v) for k, v in data.items() if k in ALLOWED_KEYS}
    if not updates:
        return jsonify({'message': 'No valid keys provided'}), 400
    conn = cur = None
    try:
        conn = get_db_connection()
        _ensure_store_settings_table(conn)
        cur  = conn.cursor()
        for key, value in updates.items():
            cur.execute("""
                INSERT INTO store_settings (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
            """, (key, value, datetime.now()))
        conn.commit()
        return jsonify({'message': 'Settings saved', 'updated': list(updates.keys())}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: release_db_connection(conn)
