from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_perms_bp = Blueprint('admin_perms', __name__)

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
    {'id': 'token-usage',         'name': 'Token Usage',         'icon': 'fa-microchip'},
]

@admin_perms_bp.route('/admin/permissions/screens', methods=['GET'])
@admin_required
def get_permission_screens(payload):
    """Get the list of all screens that can be permission-controlled"""
    return jsonify(PERMISSION_SCREENS), 200

@admin_perms_bp.route('/admin/permissions', methods=['GET'])
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

@admin_perms_bp.route('/admin/permissions/<int:user_id>', methods=['GET'])
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

@admin_perms_bp.route('/admin/permissions/<int:user_id>', methods=['PUT'])
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

@admin_perms_bp.route('/admin/permissions/<int:user_id>/check', methods=['GET'])
@token_required
def check_user_permission(payload, user_id):
    """Check if a user has access to a specific screen.

    Policy (must match the permission_required decorator and the sidebar):
      • Admin / Super Admin / Manager  → always allowed (privileged tier).
      • Everyone else                  → DENY-BY-DEFAULT: access only if an
        explicit user_permissions row grants it (has_access = TRUE).

    A non-admin user may only check their OWN permissions; checking another
    user's access requires an admin-tier role (prevents permission probing)."""
    screen = request.args.get('screen')
    if not screen:
        return jsonify({'message': 'Screen parameter is required'}), 400

    # Authorization: non-admins can only check themselves.
    is_admin_tier = payload.get('role') in ('Admin', 'Super Admin', 'Manager')
    if not is_admin_tier and payload.get('user_id') != user_id:
        return jsonify({'message': 'Access denied'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'has_access': False}), 200

        # Privileged tier always has access (matches permission_required).
        if user['role'] in ('Admin', 'Super Admin', 'Manager'):
            return jsonify({'has_access': True}), 200

        cur.execute("""
            SELECT has_access FROM user_permissions
            WHERE user_id = %s AND page_id = %s
        """, (user_id, screen))
        perm = cur.fetchone()

        # DENY-BY-DEFAULT: no explicit grant → no access.
        has_access = bool(perm and perm['has_access'])
        return jsonify({'has_access': has_access}), 200
    except Exception as e:
        # Fail closed: on error, deny rather than silently grant access.
        return jsonify({'has_access': False, 'error': str(e)}), 200
    finally:
        cur.close()
