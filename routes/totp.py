import io
import base64
import logging

import pyotp
import qrcode
from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor

from auth import token_required, admin_required, verify_password, setup_or_token_required, generate_token, set_session_cookie
from db import get_db_connection, release_db_connection
from limiter import limiter

logger = logging.getLogger(__name__)
totp_bp = Blueprint('totp', __name__)


@totp_bp.route('/totp/status', methods=['GET'])
@token_required
def totp_status(payload):
    user_id = payload['user_id']
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT totp_enabled FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'message': 'User not found'}), 404
        return jsonify({'totp_enabled': bool(row['totp_enabled'])}), 200
    finally:
        cur.close()
        release_db_connection(conn)


@totp_bp.route('/totp/setup', methods=['GET'])
@setup_or_token_required
def totp_setup(payload):
    """Generate a new secret and return a QR code (base64 PNG) for scanning.
    Accepts both regular tokens and setup-scoped tokens (forced enrollment)."""
    user_id        = payload['user_id']
    is_forced      = payload.get('scope') == 'totp_setup'

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT username, totp_enabled FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'message': 'User not found'}), 404
        if row['totp_enabled'] and not is_forced:
            return jsonify({'message': 'Authenticator app is already enabled. Disable it first.'}), 409

        secret = pyotp.random_base32()
        cur.execute("UPDATE users SET totp_secret = %s WHERE user_id = %s", (secret, user_id))
        conn.commit()

        uri = pyotp.TOTP(secret).provisioning_uri(name=row['username'], issuer_name='TrintzPOS')
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        return jsonify({'secret': secret, 'qr_code': f'data:image/png;base64,{qr_b64}'}), 200
    except Exception:
        conn.rollback()
        logger.exception("TOTP setup error")
        return jsonify({'message': 'Setup failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@totp_bp.route('/totp/enable', methods=['POST'])
@limiter.limit("10 per minute")
@setup_or_token_required
def totp_enable(payload):
    """Verify one code from the app to confirm setup, then enable TOTP.
    When called with a setup-scoped token (forced enrollment), returns a full session token."""
    user_id    = payload['user_id']
    is_forced  = payload.get('scope') == 'totp_setup'
    data       = request.get_json() or {}
    code       = str(data.get('code', '')).strip()

    if len(code) != 6 or not code.isdigit():
        return jsonify({'message': 'A 6-digit code is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT username, role, totp_secret, totp_enabled FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row or not row['totp_secret']:
            return jsonify({'message': 'No setup in progress. Please start setup first.'}), 400
        if row['totp_enabled'] and not is_forced:
            return jsonify({'message': 'Authenticator app is already enabled.'}), 409

        totp = pyotp.TOTP(row['totp_secret'])
        if not totp.verify(code, valid_window=1):
            return jsonify({'message': 'Incorrect code. Please try again.'}), 400

        cur.execute("UPDATE users SET totp_enabled = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()

        if is_forced:
            token = generate_token(user_id, row['role'], row['username'])
            resp = jsonify({
                'message': 'Authenticator app enabled! Signing you in...',
                'token':   token,
                'user':    {'user_id': user_id, 'username': row['username'], 'role': row['role']}
            })
            return set_session_cookie(resp, token), 200

        return jsonify({'message': 'Authenticator app enabled successfully!'}), 200
    except Exception:
        conn.rollback()
        logger.exception("TOTP enable error")
        return jsonify({'message': 'Failed to enable. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@totp_bp.route('/totp/disable', methods=['POST'])
@limiter.limit("10 per minute")
@token_required
def totp_disable(payload):
    """Disable TOTP — requires password confirmation."""
    user_id  = payload['user_id']
    data     = request.get_json() or {}
    password = data.get('password', '')

    if not password:
        return jsonify({'message': 'Password is required to disable authenticator app'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT password_hash FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row or not verify_password(password, row['password_hash']):
            return jsonify({'message': 'Incorrect password'}), 401

        cur.execute(
            "UPDATE users SET totp_enabled = FALSE, totp_secret = NULL WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
        return jsonify({'message': 'Authenticator app disabled.'}), 200
    except Exception:
        conn.rollback()
        logger.exception("TOTP disable error")
        return jsonify({'message': 'Failed to disable. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@totp_bp.route('/totp/admin-reset/<int:target_user_id>', methods=['POST'])
@admin_required
def totp_admin_reset(payload, target_user_id):
    """Admin: force-disable TOTP for any user (account recovery)."""
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (target_user_id,))
        if not cur.fetchone():
            return jsonify({'message': 'User not found'}), 404

        cur.execute(
            "UPDATE users SET totp_enabled = FALSE, totp_secret = NULL WHERE user_id = %s",
            (target_user_id,)
        )
        conn.commit()
        return jsonify({'message': 'TOTP has been reset for this user.'}), 200
    except Exception:
        conn.rollback()
        logger.exception("Admin TOTP reset error")
        return jsonify({'message': 'Reset failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)
