import logging
import re
from datetime import datetime, timedelta

import psycopg2
import pyotp
from flask import Blueprint, request, jsonify
from psycopg2.extras import RealDictCursor

from auth import hash_password, verify_password, generate_token
from db import get_db_connection, release_db_connection
from email_otp import (generate_otp, hash_otp, verify_otp_code, send_registration_otp,
                       hash_login_otp, verify_login_otp_code, send_login_otp,
                       hash_reset_otp, verify_reset_otp_code, send_password_reset_otp)
from limiter import limiter

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)

def parse_user_agent(user_agent):
    """Extract browser, OS, and device type from user agent string."""
    browser = 'Unknown'
    os = 'Unknown'
    device_type = 'Desktop'
    
    if not user_agent:
        return browser, os, device_type
    
    # Detect browser
    if 'Edg' in user_agent:
        browser = 'Microsoft Edge'
    elif 'Chrome' in user_agent and 'Edg' not in user_agent:
        browser = 'Google Chrome'
    elif 'Firefox' in user_agent:
        browser = 'Mozilla Firefox'
    elif 'Safari' in user_agent and 'Chrome' not in user_agent:
        browser = 'Safari'
    elif 'Opera' in user_agent or 'OPR' in user_agent:
        browser = 'Opera'
    
    # Detect OS
    if 'Windows' in user_agent:
        os = 'Windows'
    elif 'Macintosh' in user_agent or 'Mac OS X' in user_agent:
        os = 'macOS'
    elif 'Linux' in user_agent:
        os = 'Linux'
    elif 'Android' in user_agent:
        os = 'Android'
        device_type = 'Mobile'
    elif 'iPhone' in user_agent or 'iPad' in user_agent:
        os = 'iOS'
        device_type = 'Mobile'
    
    # Detect device type
    if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
        device_type = 'Mobile'
    elif 'Tablet' in user_agent or 'iPad' in user_agent:
        device_type = 'Tablet'
    
    return browser, os, device_type

def get_client_ip():
    """Get client IP address, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

def mask_email(email: str) -> str:
    if not email or '@' not in email:
        return email or ''
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = local[0] + '*' * max(1, len(local) - 1)
    else:
        masked = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute; 50 per hour")
def login():
    data = request.get_json(silent=True) or {}
    # Coalesce None to '' — a JSON null value (e.g. {"username": null}) makes
    # data.get('username', '') return None, and None.strip() would 500.
    username          = (data.get('username') or '').strip()
    password          = data.get('password') or ''
    device_fingerprint = str(data.get('device_fingerprint') or '').strip()

    if not username or not password:
        return jsonify({'message': 'Username and password are required'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        return jsonify({'message': 'Database connection failed', 'error': str(e)}), 503

    ip_address = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')
    browser, os_name, device_type = parse_user_agent(user_agent)

    try:
        cur.execute(
            """SELECT user_id, username, password_hash, role, email, full_name,
                      totp_enabled, totp_required
               FROM users WHERE username = %s""",
            (username,)
        )
        user = cur.fetchone()

        # Account lockout — 5 failures within 15 minutes triggers a 15-min block
        if user:
            cur.execute("""
                SELECT COUNT(*) FROM login_activity
                WHERE username = %s AND login_status = 'failed'
                  AND login_timestamp > NOW() - INTERVAL '15 minutes'
            """, (username,))
            recent_failures = cur.fetchone()['count']
            if recent_failures >= 5:
                try:
                    cur.execute("""
                        INSERT INTO login_activity
                          (username, ip_address, user_agent, browser, os, device_type,
                           login_status, failure_reason)
                        VALUES (%s,%s,%s,%s,%s,%s,'failed','Account temporarily locked')
                    """, (username, ip_address, user_agent, browser, os_name, device_type))
                    conn.commit()
                except Exception:
                    conn.rollback()
                return jsonify({
                    'message': 'Account temporarily locked due to too many failed attempts. '
                               'Try again in 15 minutes.'
                }), 429

        if not (user and verify_password(password, user['password_hash'])):
            try:
                cur.execute("""
                    INSERT INTO login_activity
                      (username, ip_address, user_agent, browser, os, device_type, login_status, failure_reason)
                    VALUES (%s,%s,%s,%s,%s,%s,'failed','Invalid credentials')
                """, (username, ip_address, user_agent, browser, os_name, device_type))
                conn.commit()
            except Exception:
                conn.rollback()
            return jsonify({'message': 'Invalid credentials'}), 401

        user_id    = user['user_id']
        user_email = (user.get('email') or '').strip()

        # ── Trusted-device check (runs FIRST — skips all MFA if trusted) ──────
        if device_fingerprint:
            cur.execute("""
                SELECT id FROM trusted_devices
                WHERE user_id=%s AND device_fingerprint=%s AND expires_at > NOW() AT TIME ZONE 'UTC'
            """, (user_id, device_fingerprint))
            if cur.fetchone():
                _log_success(cur, conn, user, ip_address, user_agent, browser, os_name, device_type)
                token = generate_token(user_id, user['role'], user['username'])
                return jsonify({
                    'token': token,
                    'user': {'user_id': user_id, 'username': user['username'], 'role': user['role']}
                }), 200

        # ── TOTP / enforced MFA (only reached on untrusted device) ────────────
        if user['totp_enabled']:
            return jsonify({
                'requires_totp': True,
                'user_id':       user_id,
                'message':       'Enter the 6-digit code from your authenticator app'
            }), 200
        if user['totp_required']:
            from auth import generate_setup_token
            setup_token = generate_setup_token(user_id)
            return jsonify({
                'requires_totp_setup': True,
                'setup_token':         setup_token,
                'message':             'Your account requires Google Authenticator. Please set it up to continue.'
            }), 200

        # ── Email OTP (no TOTP, untrusted device) ────────────────────────────
        # Skip if user has no email or no fingerprint (legacy/admin accounts)
        if not user_email or not device_fingerprint:
            _log_success(cur, conn, user, ip_address, user_agent, browser, os_name, device_type)
            token = generate_token(user_id, user['role'], user['username'])
            return jsonify({
                'token': token,
                'user': {'user_id': user_id, 'username': user['username'], 'role': user['role']}
            }), 200

        otp_code     = generate_otp()
        otp_hash_val = hash_login_otp(otp_code, user_id)
        expires_at   = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("UPDATE login_otps SET is_used=TRUE WHERE user_id=%s AND is_used=FALSE", (user_id,))
        cur.execute("""
            INSERT INTO login_otps (user_id, otp_hash, expires_at)
            VALUES (%s, %s, %s)
        """, (user_id, otp_hash_val, expires_at))
        conn.commit()

        send_login_otp(user_email, user.get('full_name') or username, otp_code)

        return jsonify({
            'requires_otp': True,
            'user_id':      user_id,
            'email':        mask_email(user_email),
            'message':      'Verification code sent to your registered email'
        }), 200

    except Exception:
        logger.exception("Login error")
        return jsonify({'message': 'Login failed'}), 500
    finally:
        try:
            cur.close()
            release_db_connection(conn)
        except Exception:
            pass


def _log_success(cur, conn, user, ip_address, user_agent, browser, os_name, device_type):
    try:
        cur.execute("""
            INSERT INTO login_activity
              (user_id, username, ip_address, user_agent, browser, os, device_type, login_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'success')
        """, (user['user_id'], user['username'], ip_address, user_agent, browser, os_name, device_type))
        conn.commit()
    except Exception as e:
        logger.warning("Failed to log login activity: %s", e)
        conn.rollback()


def _save_trusted_device(cur, conn, user_id, device_fingerprint, remember_device):
    """Upsert a trusted-device record valid for 2 days. No-op if fingerprint is empty or remember is False."""
    if not device_fingerprint or not remember_device:
        return
    ip_address = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')
    browser, os_name, device_type = parse_user_agent(user_agent)
    expires_at = datetime.utcnow() + timedelta(days=2)
    cur.execute("""
        INSERT INTO trusted_devices
          (user_id, device_fingerprint, browser, os, device_type, last_ip, expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (user_id, device_fingerprint) DO UPDATE
          SET expires_at=%s, last_seen=NOW(), last_ip=%s,
              browser=%s, os=%s, device_type=%s
    """, (user_id, device_fingerprint, browser, os_name, device_type, ip_address, expires_at,
          expires_at, ip_address, browser, os_name, device_type))


@auth_bp.route('/verify-login-otp', methods=['POST'])
@limiter.limit("10 per minute")
def verify_login_otp():
    data              = request.get_json() or {}
    user_id           = data.get('user_id')
    otp               = str(data.get('otp', '')).strip()
    device_fingerprint = str(data.get('device_fingerprint', '')).strip()
    remember_device   = bool(data.get('remember_device', True))

    if not user_id or not otp:
        return jsonify({'message': 'user_id and otp are required'}), 400
    if not re.match(r'^\d{6}$', otp):
        return jsonify({'message': 'OTP must be exactly 6 digits'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM login_otps
            WHERE user_id=%s AND is_used=FALSE AND expires_at > NOW() AT TIME ZONE 'UTC'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        record = cur.fetchone()

        if not record:
            return jsonify({'message': 'Code has expired. Please log in again.'}), 400

        cur.execute("UPDATE login_otps SET attempts=attempts+1 WHERE id=%s", (record['id'],))

        if record['attempts'] + 1 > 5:
            conn.commit()
            return jsonify({'message': 'Too many failed attempts. Please log in again.'}), 429

        if not verify_login_otp_code(otp, user_id, record['otp_hash']):
            conn.commit()
            return jsonify({'message': 'Incorrect code. Please check your email.'}), 400

        cur.execute("UPDATE login_otps SET is_used=TRUE WHERE id=%s", (record['id'],))

        _save_trusted_device(cur, conn, user_id, device_fingerprint, remember_device)

        cur.execute("SELECT user_id, username, role FROM users WHERE user_id=%s", (user_id,))
        user = cur.fetchone()
        conn.commit()

        if not user:
            return jsonify({'message': 'User not found'}), 404

        token = generate_token(user['user_id'], user['role'], user['username'])
        return jsonify({
            'token': token,
            'user': {'user_id': user['user_id'], 'username': user['username'], 'role': user['role']}
        }), 200

    except Exception:
        conn.rollback()
        logger.exception("Verify login OTP error")
        return jsonify({'message': 'Verification failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/verify-totp-login', methods=['POST'])
@limiter.limit("10 per minute")
def verify_totp_login():
    data               = request.get_json() or {}
    user_id            = data.get('user_id')
    code               = str(data.get('code', '')).strip()
    device_fingerprint = str(data.get('device_fingerprint', '')).strip()
    remember_device    = bool(data.get('remember_device', True))

    if not user_id or not code:
        return jsonify({'message': 'user_id and code are required'}), 400
    if not re.match(r'^\d{6}$', code):
        return jsonify({'message': 'Code must be exactly 6 digits'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT user_id, username, role, totp_secret FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cur.fetchone()
        if not user or not user['totp_secret']:
            return jsonify({'message': 'TOTP not configured for this account'}), 400

        totp = pyotp.TOTP(user['totp_secret'])
        if not totp.verify(code, valid_window=1):
            return jsonify({'message': 'Incorrect code. Please try again.'}), 400

        ip_address = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        browser, os_name, device_type = parse_user_agent(user_agent)
        _log_success(cur, conn, user, ip_address, user_agent, browser, os_name, device_type)

        _save_trusted_device(cur, conn, user_id, device_fingerprint, remember_device)
        conn.commit()

        token = generate_token(user['user_id'], user['role'], user['username'])
        return jsonify({
            'token': token,
            'user': {
                'user_id':  user['user_id'],
                'username': user['username'],
                'role':     user['role']
            }
        }), 200
    except Exception:
        conn.rollback()
        logger.exception("TOTP login verify error")
        return jsonify({'message': 'Verification failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/resend-login-otp', methods=['POST'])
@limiter.limit("3 per minute")
def resend_login_otp():
    data    = request.get_json() or {}
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'message': 'user_id is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT user_id, username, email, full_name FROM users WHERE user_id=%s", (user_id,))
        user = cur.fetchone()
        if not user or not user.get('email'):
            return jsonify({'message': 'User not found or no email on record'}), 404

        cur.execute("UPDATE login_otps SET is_used=TRUE WHERE user_id=%s AND is_used=FALSE", (user_id,))

        otp_code     = generate_otp()
        otp_hash_val = hash_login_otp(otp_code, user_id)
        expires_at   = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("""
            INSERT INTO login_otps (user_id, otp_hash, expires_at)
            VALUES (%s,%s,%s)
        """, (user_id, otp_hash_val, expires_at))
        conn.commit()

        send_login_otp(user['email'], user.get('full_name') or user['username'], otp_code)
        return jsonify({'message': 'New verification code sent to your email.'}), 200

    except Exception:
        conn.rollback()
        logger.exception("Resend login OTP error")
        return jsonify({'message': 'Could not resend code. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)

# ── Registration ──────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,50}$')


@auth_bp.route('/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    """Step 1 — collect user details, send OTP to email."""
    data = request.get_json() or {}

    username  = str(data.get('username', '')).strip()
    email     = str(data.get('email', '')).strip().lower()
    password  = str(data.get('password', ''))
    full_name = str(data.get('full_name', '')).strip()
    mobile    = str(data.get('mobile', '')).strip() or None

    # Basic validation
    if not username or not email or not password or not full_name:
        return jsonify({'message': 'username, email, password, and full_name are required'}), 400
    if not USERNAME_RE.match(username):
        return jsonify({'message': 'Username must be 3-50 characters: letters, numbers, underscore only'}), 400
    if not EMAIL_RE.match(email):
        return jsonify({'message': 'Invalid email address'}), 400
    if len(password) < 8:
        return jsonify({'message': 'Password must be at least 8 characters'}), 400
    if not re.search(r'[A-Z]', password):
        return jsonify({'message': 'Password must contain at least one uppercase letter'}), 400
    if not re.search(r'[a-z]', password):
        return jsonify({'message': 'Password must contain at least one lowercase letter'}), 400
    if not re.search(r'\d', password):
        return jsonify({'message': 'Password must contain at least one number'}), 400
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]', password):
        return jsonify({'message': 'Password must contain at least one special character'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Check username/email uniqueness in users table
        cur.execute("SELECT username FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'message': 'Username already taken'}), 409

        cur.execute("SELECT username FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({'message': 'An account with this email already exists'}), 409

        # Invalidate any previous unused OTP for this email
        cur.execute(
            "UPDATE registration_otps SET is_used=TRUE WHERE email=%s AND is_used=FALSE",
            (email,)
        )

        otp_code    = generate_otp()
        otp_hash_val = hash_otp(otp_code, email)
        expires_at  = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("""
            INSERT INTO registration_otps
              (email, username, full_name, mobile, password_hash, otp_hash, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (email, username, full_name, mobile,
              hash_password(password), otp_hash_val, expires_at))
        conn.commit()

        # Send OTP email (non-fatal if email fails in dev)
        ok = send_registration_otp(email, full_name, otp_code)
        if not ok:
            return jsonify({'message': 'Failed to send verification email. Please try again.'}), 503

        return jsonify({'message': 'OTP sent to your email. Please verify to complete registration.'}), 200

    except Exception:
        conn.rollback()
        logger.exception("Registration error")
        return jsonify({'message': 'Registration failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/verify-registration', methods=['POST'])
@limiter.limit("10 per minute")
def verify_registration():
    """Step 2 — verify OTP and create the user account."""
    data  = request.get_json() or {}
    email = str(data.get('email', '')).strip().lower()
    otp   = str(data.get('otp', '')).strip()

    if not email or not otp:
        return jsonify({'message': 'email and otp are required'}), 400
    if not re.match(r'^\d{6}$', otp):
        return jsonify({'message': 'OTP must be exactly 6 digits'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM registration_otps
            WHERE email=%s AND is_used=FALSE AND expires_at > NOW() AT TIME ZONE 'UTC'
            ORDER BY created_at DESC LIMIT 1
        """, (email,))
        record = cur.fetchone()

        if not record:
            return jsonify({'message': 'OTP has expired or does not exist. Please register again.'}), 400

        # Increment attempt counter
        cur.execute(
            "UPDATE registration_otps SET attempts=attempts+1 WHERE id=%s",
            (record['id'],)
        )

        if record['attempts'] + 1 > 5:
            conn.commit()
            return jsonify({'message': 'Too many failed attempts. Please register again.'}), 429

        if not verify_otp_code(otp, email, record['otp_hash']):
            conn.commit()
            return jsonify({'message': 'Incorrect OTP. Please check your email.'}), 400

        # OTP correct — mark used and create user
        cur.execute("UPDATE registration_otps SET is_used=TRUE WHERE id=%s", (record['id'],))

        cur.execute("""
            INSERT INTO users (username, password_hash, role, full_name, email, mobile)
            VALUES (%s, %s, 'Cashier', %s, %s, %s)
            RETURNING user_id, username, role
        """, (record['username'], record['password_hash'],
              record['full_name'], email, record['mobile']))

        new_user = cur.fetchone()
        conn.commit()

        token = generate_token(new_user['user_id'], new_user['role'], new_user['username'])
        logger.info("New user registered: %s (%s)", new_user['username'], email)

        return jsonify({
            'message': 'Registration complete! Welcome to TrintzPOS.',
            'token': token,
            'user': {
                'user_id': new_user['user_id'],
                'username': new_user['username'],
                'role': new_user['role']
            }
        }), 201

    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'message': 'Username or email already exists'}), 409
    except Exception:
        conn.rollback()
        logger.exception("Verify registration error")
        return jsonify({'message': 'Verification failed. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/resend-registration-otp', methods=['POST'])
@limiter.limit("3 per minute")
def resend_registration_otp():
    """Resend OTP for a pending registration."""
    data  = request.get_json() or {}
    email = str(data.get('email', '')).strip().lower()

    if not email:
        return jsonify({'message': 'email is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM registration_otps
            WHERE email=%s AND is_used=FALSE
            ORDER BY created_at DESC LIMIT 1
        """, (email,))
        record = cur.fetchone()

        if not record:
            return jsonify({'message': 'No pending registration found. Please register again.'}), 404

        # Issue fresh OTP
        cur.execute(
            "UPDATE registration_otps SET is_used=TRUE WHERE id=%s",
            (record['id'],)
        )
        otp_code     = generate_otp()
        otp_hash_val  = hash_otp(otp_code, email)
        expires_at   = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("""
            INSERT INTO registration_otps
              (email, username, full_name, mobile, password_hash, otp_hash, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (email, record['username'], record['full_name'], record['mobile'],
              record['password_hash'], otp_hash_val, expires_at))
        conn.commit()

        ok = send_registration_otp(email, record['full_name'] or 'User', otp_code)
        if not ok:
            return jsonify({'message': 'Failed to send email. Please try again.'}), 503

        return jsonify({'message': 'New OTP sent to your email.'}), 200

    except Exception:
        conn.rollback()
        logger.exception("Resend OTP error")
        return jsonify({'message': 'Could not resend OTP. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("5 per minute")
def forgot_password():
    data     = request.get_json() or {}
    username = str(data.get('username', '')).strip()

    if not username:
        return jsonify({'message': 'Username is required'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT user_id, username, email, full_name FROM users WHERE username = %s",
            (username,)
        )
        user = cur.fetchone()

        # Return the same message whether user exists or not — prevents enumeration
        if not user or not (user.get('email') or '').strip():
            return jsonify({
                'message': 'If this username exists with a registered email, a reset code has been sent.'
            }), 200

        user_id    = user['user_id']
        user_email = user['email'].strip()

        # Invalidate any previous unused reset OTPs
        cur.execute(
            "UPDATE password_reset_otps SET is_used=TRUE WHERE user_id=%s AND is_used=FALSE",
            (user_id,)
        )

        otp_code     = generate_otp()
        otp_hash_val = hash_reset_otp(otp_code, user_id)
        expires_at   = datetime.utcnow() + timedelta(minutes=5)

        cur.execute("""
            INSERT INTO password_reset_otps (user_id, otp_hash, expires_at)
            VALUES (%s, %s, %s)
        """, (user_id, otp_hash_val, expires_at))
        conn.commit()

        send_password_reset_otp(user_email, user.get('full_name') or username, otp_code)

        return jsonify({
            'user_id': user_id,
            'email':   mask_email(user_email),
            'message': 'Reset code sent to your registered email.'
        }), 200

    except Exception:
        conn.rollback()
        logger.exception("Forgot password error")
        return jsonify({'message': 'Failed to process request. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/reset-password', methods=['POST'])
@limiter.limit("10 per minute")
def reset_password():
    data         = request.get_json() or {}
    user_id      = data.get('user_id')
    otp          = str(data.get('otp', '')).strip()
    new_password = str(data.get('new_password', ''))

    if not user_id or not otp or not new_password:
        return jsonify({'message': 'user_id, otp, and new_password are required'}), 400
    if not re.match(r'^\d{6}$', otp):
        return jsonify({'message': 'OTP must be exactly 6 digits'}), 400

    # Password strength
    if len(new_password) < 8:
        return jsonify({'message': 'Password must be at least 8 characters'}), 400
    if not re.search(r'[A-Z]', new_password):
        return jsonify({'message': 'Password must contain at least one uppercase letter'}), 400
    if not re.search(r'[a-z]', new_password):
        return jsonify({'message': 'Password must contain at least one lowercase letter'}), 400
    if not re.search(r'\d', new_password):
        return jsonify({'message': 'Password must contain at least one number'}), 400
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]', new_password):
        return jsonify({'message': 'Password must contain at least one special character'}), 400

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM password_reset_otps
            WHERE user_id=%s AND is_used=FALSE AND expires_at > NOW() AT TIME ZONE 'UTC'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        record = cur.fetchone()

        if not record:
            return jsonify({'message': 'Reset code has expired. Please request a new one.'}), 400

        cur.execute(
            "UPDATE password_reset_otps SET attempts=attempts+1 WHERE id=%s",
            (record['id'],)
        )

        if record['attempts'] + 1 > 5:
            conn.commit()
            return jsonify({'message': 'Too many failed attempts. Please request a new code.'}), 429

        if not verify_reset_otp_code(otp, user_id, record['otp_hash']):
            conn.commit()
            return jsonify({'message': 'Incorrect code. Please check your email.'}), 400

        # OTP correct — mark used and update password
        cur.execute("UPDATE password_reset_otps SET is_used=TRUE WHERE id=%s", (record['id'],))

        new_hash = hash_password(new_password)
        cur.execute("UPDATE users SET password_hash=%s WHERE user_id=%s", (new_hash, user_id))
        conn.commit()

        logger.info("Password reset completed for user_id=%s", user_id)
        return jsonify({'message': 'Password reset successfully. You can now log in.'}), 200

    except Exception:
        conn.rollback()
        logger.exception("Reset password error")
        return jsonify({'message': 'Failed to reset password. Please try again.'}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@auth_bp.route('/users/me', methods=['GET'])
def get_current_user():
    token = None
    if 'Authorization' in request.headers:
        auth_header = request.headers['Authorization']
        try:
            token = auth_header.split(" ")[1]  # Bearer <token>
        except IndexError:
            return jsonify({'message': 'Token is missing!'}), 401

    if not token:
        return jsonify({'message': 'Token is missing!'}), 401

    from auth import verify_token  # Import here to avoid circular import
    payload = verify_token(token)
    if not payload:
        return jsonify({'message': 'Token is invalid!'}), 401

    return jsonify({
        'user_id': payload.get('user_id'),
        'username': payload.get('username'),
        'role': payload.get('role')
    }), 200