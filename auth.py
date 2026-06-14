import jwt
import datetime
from functools import wraps
from flask import request, jsonify
import os
from passlib.hash import pbkdf2_sha256
from db import get_db_connection, release_db_connection

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

def hash_password(password):
    return pbkdf2_sha256.hash(password)

def verify_password(password, hash):
    try:
        return pbkdf2_sha256.verify(password, hash)
    except Exception:
        return False

def generate_token(user_id, role, username):
    payload = {
        'user_id': user_id,
        'role': role,
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def verify_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def generate_setup_token(user_id):
    """Short-lived JWT (10 min) used only during forced TOTP enrollment at login."""
    payload = {
        'user_id': user_id,
        'scope':   'totp_setup',
        'exp':     datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Token is missing!'}), 401

        # Fall back to a ?token= query param. Browser-initiated file downloads
        # (e.g. backup download via window.location) cannot set an Authorization
        # header, so the token is passed in the URL for those GET requests.
        if not token:
            token = request.args.get('token')

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        # Reject setup-scoped tokens from regular protected endpoints
        if payload.get('scope') == 'totp_setup':
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(payload, *args, **kwargs)

    return decorated

def setup_or_token_required(f):
    """Accepts both regular session tokens AND setup-scoped tokens (for forced enrollment)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'message': 'Token is missing!'}), 401

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(payload, *args, **kwargs)

    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Token is missing!'}), 401

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        if payload.get('role') not in ('Admin', 'Super Admin', 'Manager'):
            return jsonify({'message': 'Admin access required!'}), 403

        return f(payload, *args, **kwargs)

    return decorated

def cashier_required(f):
    """
    Decorator to restrict access to sales-capable roles:
    Cashier, Admin, Super Admin, Manager.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Token is missing!'}), 401

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        # Reject setup-scoped tokens
        if payload.get('scope') == 'totp_setup':
            return jsonify({'message': 'Token is invalid!'}), 401

        role = payload.get('role')
        if role not in ('Cashier', 'Admin', 'Super Admin', 'Manager'):
            return jsonify({'message': 'Access required: Cashier, Manager, or Admin role'}), 403

        return f(payload, *args, **kwargs)

    return decorated

def permission_required(screen):
    """
    Decorator to check if a user has access to a specific screen.
    Admin role always has full access (bypasses permission checks).
    For other roles, checks the user_permissions table.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = None
            if 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                try:
                    token = auth_header.split(" ")[1]
                except IndexError:
                    return jsonify({'message': 'Token is missing!'}), 401

            if not token:
                return jsonify({'message': 'Token is missing!'}), 401

            payload = verify_token(token)
            if not payload:
                return jsonify({'message': 'Token is invalid!'}), 401

            # Admin-tier roles always have access
            if payload.get('role') in ('Admin', 'Super Admin', 'Manager'):
                return f(payload, *args, **kwargs)

            # Check permission for the specific screen
            user_id = payload.get('user_id')
            if not user_id:
                return jsonify({'message': 'Invalid token payload'}), 401

            try:
                from db import get_db_connection, release_db_connection
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT has_access FROM user_permissions WHERE user_id = %s AND page_id = %s",
                    (user_id, screen)
                )
                perm = cur.fetchone()
                cur.close()
                release_db_connection(conn)

                # If no record exists, deny by default (secure default)
                if perm is not None and perm[0]:
                    return f(payload, *args, **kwargs)
                else:
                    return jsonify({'message': f'Access denied for {screen}'}), 403
            except Exception as e:
                # Fail-secure: deny on DB error rather than granting access
                print(f'Permission check error: {e}')
                return jsonify({'message': 'Permission check failed'}), 403

        return decorated
    return decorator