from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

admin_users_bp = Blueprint('admin_users', __name__)

@admin_users_bp.route('/admin/users', methods=['GET'])
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

@admin_users_bp.route('/admin/users/<int:user_id>', methods=['GET'])
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

@admin_users_bp.route('/admin/users', methods=['POST'])
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

@admin_users_bp.route('/admin/users/<int:user_id>/reset-password', methods=['PUT'])
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

@admin_users_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
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

@admin_users_bp.route('/admin/users/<int:user_id>/delete-preview', methods=['GET'])
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


@admin_users_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
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

@admin_users_bp.route('/admin/users/<int:user_id>/totp-required', methods=['PUT'])
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
