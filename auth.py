import jwt
import datetime
import os
from functools import wraps
from flask import request, jsonify
from passlib.hash import pbkdf2_sha256
from db import get_db_connection, release_db_connection

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

# Cookie name used for httpOnly session cookie
SESSION_COOKIE = 'pos_session'

# True when running behind HTTPS (Render/production). Secure=False in local dev
# so the cookie works over plain http://localhost
_is_secure = os.environ.get('FLASK_ENV', 'production') != 'development' and \
             os.environ.get('DB_HOST', 'localhost') not in ('localhost', '127.0.0.1')


def hash_password(password):
    return pbkdf2_sha256.hash(password)


def verify_password(password, hash):
    try:
        return pbkdf2_sha256.verify(password, hash)
    except Exception:
        return False


def generate_token(user_id, role, username):
    payload = {
        'user_id':  user_id,
        'role':     role,
        'username': username,
        'exp':      datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def generate_setup_token(user_id):
    """Short-lived JWT (10 min) used only during forced TOTP enrollment at login."""
    payload = {
        'user_id': user_id,
        'scope':   'totp_setup',
        'exp':     datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def verify_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def set_session_cookie(response, token):
    """Attach an httpOnly session cookie to a response."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=_is_secure,
        samesite='Strict',
        max_age=86400,   # 24 hours — matches JWT expiry
        path='/',
    )
    return response


def clear_session_cookie(response):
    """Expire the session cookie (used on logout)."""
    response.set_cookie(
        SESSION_COOKIE,
        '',
        httponly=True,
        secure=_is_secure,
        samesite='Strict',
        max_age=0,
        path='/',
    )
    return response


def _extract_token():
    """
    Extract JWT from the request. Priority order:
      1. httpOnly cookie  (most secure — JS cannot read it)
      2. Authorization: Bearer <token> header  (backward compat for existing JS)
      3. ?token= query param  (file-download endpoints that can't set headers)
    Returns the raw token string or None.
    """
    # 1. httpOnly cookie
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        return token

    # 2. Authorization header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        if token:
            return token

    # 3. Query param (download endpoints)
    token = request.args.get('token')
    return token or None


# ── Decorators ────────────────────────────────────────────────────────────────

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        if payload.get('scope') == 'totp_setup':
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(payload, *args, **kwargs)
    return decorated


def setup_or_token_required(f):
    """Accepts both regular session tokens AND setup-scoped tokens."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
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
        token = _extract_token()
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
    """Restrict to sales-capable roles: Cashier, Admin, Super Admin, Manager."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid!'}), 401

        if payload.get('scope') == 'totp_setup':
            return jsonify({'message': 'Token is invalid!'}), 401

        if payload.get('role') not in ('Cashier', 'Admin', 'Super Admin', 'Manager'):
            return jsonify({'message': 'Access required: Cashier, Manager, or Admin role'}), 403

        return f(payload, *args, **kwargs)
    return decorated


def permission_required(screen):
    """Check if a user has access to a specific screen."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({'message': 'Token is missing!'}), 401

            payload = verify_token(token)
            if not payload:
                return jsonify({'message': 'Token is invalid!'}), 401

            if payload.get('role') in ('Admin', 'Super Admin', 'Manager'):
                return f(payload, *args, **kwargs)

            user_id = payload.get('user_id')
            if not user_id:
                return jsonify({'message': 'Invalid token payload'}), 401

            try:
                conn = get_db_connection()
                cur  = conn.cursor()
                cur.execute(
                    "SELECT has_access FROM user_permissions WHERE user_id = %s AND page_id = %s",
                    (user_id, screen)
                )
                perm = cur.fetchone()
                cur.close()
                release_db_connection(conn)

                if perm is not None and perm[0]:
                    return f(payload, *args, **kwargs)
                return jsonify({'message': f'Access denied for {screen}'}), 403
            except Exception as e:
                print(f'Permission check error: {e}')
                return jsonify({'message': 'Permission check failed'}), 403

        return decorated
    return decorator


def strict_permission_required(screen):
    """Gate a screen on the per-user permission for EVERY role except Super Admin.

    Unlike permission_required (which auto-passes the Admin/Manager privileged
    tier), this decorator honours the user_permissions toggle for Admins and
    Managers too. Only Super Admin bypasses the check.

    Policy: DENY-BY-DEFAULT — access is granted only when an explicit
    user_permissions row sets has_access = TRUE. Fails closed on error.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({'message': 'Token is missing!'}), 401

            payload = verify_token(token)
            if not payload:
                return jsonify({'message': 'Token is invalid!'}), 401

            # Super Admin always has unrestricted access.
            if payload.get('role') == 'Super Admin':
                return f(payload, *args, **kwargs)

            user_id = payload.get('user_id')
            if not user_id:
                return jsonify({'message': 'Invalid token payload'}), 401

            try:
                conn = get_db_connection()
                cur  = conn.cursor()
                cur.execute(
                    "SELECT has_access FROM user_permissions WHERE user_id = %s AND page_id = %s",
                    (user_id, screen)
                )
                perm = cur.fetchone()
                cur.close()
                release_db_connection(conn)

                if perm is not None and perm[0]:
                    return f(payload, *args, **kwargs)
                return jsonify({'message': f'Access denied for {screen}'}), 403
            except Exception as e:
                print(f'Permission check error: {e}')
                return jsonify({'message': 'Permission check failed'}), 403

        return decorated
    return decorator
