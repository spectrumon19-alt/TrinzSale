"""
JSON API routes for the License Admin Portal.
All routes require an active admin session.
"""

import json
from datetime import date, datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, session

from config import Config
from core import engine
from core.db import (
    insert_license, revoke_license, get_license,
    get_all_licenses, audit, get_stats,
    get_smtp_config, save_smtp_config,
)

api_bp = Blueprint('api', __name__)


def _require_auth():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorised'}), 401
    return None


# ── Issue a new license ────────────────────────────────────────────────────────

@api_bp.route('/issue', methods=['POST'])
def issue():
    err = _require_auth()
    if err:
        return err

    if not Path(Config.PRIVATE_KEY_PATH).exists():
        return jsonify({'error': 'Private key not found. Upload keys/private.pem first.'}), 400

    data = request.get_json(silent=True) or {}

    # Validate required fields
    for field in ('customer', 'email', 'expiry_date'):
        if not data.get(field, '').strip():
            return jsonify({'error': f'Field "{field}" is required.'}), 400

    try:
        expiry = date.fromisoformat(data['expiry_date'])
        if expiry <= date.today():
            return jsonify({'error': 'Expiry date must be in the future.'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid expiry_date format. Use YYYY-MM-DD.'}), 400

    # Build serial
    from core.db import _connect
    conn = _connect(Config.DB_PATH)
    serial = engine.next_serial(conn)
    conn.close()

    # Build payload
    payload = {
        'serial':           serial,
        'customer':         data['customer'].strip(),
        'email':            data['email'].strip(),
        'license_type':     data.get('license_type', 'Professional'),
        'expiry_date':      data['expiry_date'],
        'hardware_binding': bool(data.get('hardware_binding', False)),
        'machine_id':       data.get('machine_id') or None,
        'max_users':        int(data.get('max_users', 5)),
        'features':         data.get('features', ['pos', 'crm', 'reports', 'gst', 'tally', 'knowledge']),
        'issued_at':        date.today().isoformat(),
    }

    # Sign the license
    try:
        license_key = engine.issue_license(Config.PRIVATE_KEY_PATH, payload)
    except Exception as e:
        return jsonify({'error': f'Signing failed: {e}'}), 500

    # Persist to DB
    days = (expiry - date.today()).days
    insert_license(Config.DB_PATH, {
        'serial':           serial,
        'customer':         payload['customer'],
        'email':            payload['email'],
        'license_type':     payload['license_type'],
        'expiry_date':      payload['expiry_date'],
        'hardware_binding': int(payload['hardware_binding']),
        'machine_id':       payload['machine_id'],
        'max_users':        payload['max_users'],
        'features':         payload['features'],
        'issued_at':        payload['issued_at'],
        'issued_by':        'admin',
        'full_key':         license_key,
        'notes':            data.get('notes', ''),
    })

    audit(Config.DB_PATH,
          action='ISSUE',
          detail=f"Serial {serial} issued to {payload['customer']} <{payload['email']}> — expires {data['expiry_date']} ({days}d)",
          ip=request.remote_addr)

    return jsonify({
        'success':      True,
        'serial':       serial,
        'license_key':  license_key,
        'customer':     payload['customer'],
        'license_type': payload['license_type'],
        'expiry_date':  payload['expiry_date'],
        'days':         days,
    })


# ── Revoke ─────────────────────────────────────────────────────────────────────

@api_bp.route('/revoke/<serial>', methods=['POST'])
def revoke(serial):
    err = _require_auth()
    if err:
        return err

    data   = request.get_json(silent=True) or {}
    reason = data.get('reason', '').strip()
    ok     = revoke_license(Config.DB_PATH, serial, reason)
    if not ok:
        return jsonify({'error': 'License not found or already revoked.'}), 404

    audit(Config.DB_PATH,
          action='REVOKE',
          detail=f"Serial {serial} revoked. Reason: {reason or '—'}",
          ip=request.remote_addr)

    return jsonify({'success': True, 'serial': serial})


# ── Get full key for a serial ──────────────────────────────────────────────────

@api_bp.route('/key/<serial>', methods=['GET'])
def get_key(serial):
    err = _require_auth()
    if err:
        return err

    lic = get_license(Config.DB_PATH, serial)
    if not lic:
        return jsonify({'error': 'License not found.'}), 404

    audit(Config.DB_PATH,
          action='VIEW_KEY',
          detail=f"Key viewed for serial {serial}",
          ip=request.remote_addr)

    return jsonify({'serial': serial, 'license_key': lic['full_key']})


# ── Stats (for dashboard refresh) ─────────────────────────────────────────────

@api_bp.route('/stats', methods=['GET'])
def stats():
    err = _require_auth()
    if err:
        return err
    return jsonify(get_stats(Config.DB_PATH))


# ── Generate key pair ──────────────────────────────────────────────────────────

@api_bp.route('/generate-keypair', methods=['POST'])
def gen_keypair():
    err = _require_auth()
    if err:
        return err

    priv = Config.PRIVATE_KEY_PATH
    pub  = Config.PUBLIC_KEY_PATH

    if Path(priv).exists():
        data = request.get_json(silent=True) or {}
        if not data.get('confirm'):
            return jsonify({'error': 'Key pair already exists. Send confirm:true to overwrite.'}), 409

    try:
        engine.generate_keypair(priv, pub)
        fp = engine.public_key_fingerprint(pub)
        audit(Config.DB_PATH, action='KEYGEN', detail='New RSA-2048 key pair generated',
              ip=request.remote_addr)
        return jsonify({'success': True, 'fingerprint': fp})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Verify a license key ───────────────────────────────────────────────────────

@api_bp.route('/verify', methods=['POST'])
def verify():
    err = _require_auth()
    if err:
        return err

    if not Path(Config.PUBLIC_KEY_PATH).exists():
        return jsonify({'error': 'Public key not found.'}), 400

    data = request.get_json(silent=True) or {}
    key  = data.get('license_key', '').strip()
    if not key:
        return jsonify({'error': 'license_key is required.'}), 400

    payload = engine.verify_license(Config.PUBLIC_KEY_PATH, key)
    if not payload:
        return jsonify({'valid': False, 'error': 'Invalid signature or malformed key.'})

    exp   = date.fromisoformat(payload['expiry_date'])
    today = date.today()
    return jsonify({
        'valid':    True,
        'payload':  payload,
        'expired':  exp < today,
        'days':     max(0, (exp - today).days),
    })


# ── Native folder browser (tkinter) ───────────────────────────────────────────

@api_bp.route('/browse-folder', methods=['POST'])
def browse_folder():
    err = _require_auth()
    if err:
        return err

    import tkinter as tk
    from tkinter import filedialog

    data    = request.get_json(silent=True) or {}
    title   = data.get('title', 'Select Folder')
    initial = data.get('initial', '') or '/'

    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', True)   # bring dialog to foreground
        path = filedialog.askdirectory(parent=root, title=title, initialdir=initial)
        root.destroy()
        return jsonify({'path': path or ''})
    except Exception as e:
        return jsonify({'path': '', 'error': str(e)}), 500


# ── Build customer distribution ────────────────────────────────────────────────

@api_bp.route('/build-dist', methods=['POST'])
def build_dist():
    err = _require_auth()
    if err:
        return err

    data          = request.get_json(silent=True) or {}
    source_dir    = data.get('source_dir', '').strip()
    output_dir    = data.get('output_dir', '').strip()
    customer_name = data.get('customer_name', 'Customer').strip() or 'Customer'
    to_email      = data.get('email', '').strip()
    serial        = data.get('serial', '').strip()
    send_only     = data.get('send_only', False)   # True = email without saving folder

    if not source_dir:
        source_dir = Config.SOURCE_CODE_DIR
    if not output_dir:
        from datetime import date as _d
        safe_name = customer_name.replace(' ', '_').replace('/', '_')[:30]
        output_dir = str(Config.DIST_OUTPUT_BASE / f"{safe_name}_{_d.today().isoformat()}")

    if not source_dir:
        return jsonify({'error': 'source_dir is required (or set SOURCE_CODE_DIR in .env)'}), 400

    from core.dist_builder import DistBuilder
    builder = DistBuilder(source_dir=source_dir, output_dir=output_dir,
                          customer_name=customer_name)

    # Run build
    result = builder.build()
    if not result['success']:
        audit(Config.DB_PATH, 'BUILD_DIST_FAIL',
              f"Customer: {customer_name} | Error: {result.get('error')}",
              ip=request.remote_addr)
        return jsonify(result), 500

    # Create ZIP (always, for download or email)
    zip_result   = None
    email_result = None

    zip_path   = builder.make_zip()
    zip_size   = round(Path(zip_path).stat().st_size / 1_048_576, 1)
    zip_result = {'path': zip_path, 'size_mb': zip_size, 'filename': Path(zip_path).name}

    # If email requested, try to send via Brevo SMTP
    if to_email:
        email_result = builder.send_email(
            to_email=to_email,
            zip_path=zip_path,
            serial=serial,
        )
        # If email fails, provide download link as fallback
        if not email_result.get('success'):
            email_result['fallback'] = f'Email could not be sent. Download link: {Path(zip_path).name}'

    audit(Config.DB_PATH, 'BUILD_DIST',
          f"Customer: {customer_name} | Serial: {serial or '-'} | "
          f"Output: {output_dir} | Email: {to_email or '-'}",
          ip=request.remote_addr)

    return jsonify({
        'success':      True,
        'output_dir':   result['output_dir'],
        'stats':        result['stats'],
        'log':          result['log'],
        'zip':          zip_result,
        'email':        email_result,
    })


# ── Download distribution package ────────────────────────────────────────────

@api_bp.route('/download/<filename>', methods=['GET'])
def download_dist(filename):
    err = _require_auth()
    if err:
        return err

    # Security: only allow downloading from distributions folder
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400

    dist_path = Config.DIST_OUTPUT_BASE / (filename + '_package.zip')
    if not dist_path.exists():
        # Try without _package suffix
        dist_path = Config.DIST_OUTPUT_BASE.parent / filename
        if not dist_path.exists():
            return jsonify({'error': 'File not found'}), 404

    from flask import send_file
    return send_file(str(dist_path), as_attachment=True, download_name=dist_path.name)


# ── SMTP settings — GET / POST ─────────────────────────────────────────────────

@api_bp.route('/smtp/settings', methods=['GET', 'POST'])
def smtp_settings():
    err = _require_auth()
    if err:
        return err

    if request.method == 'GET':
        cfg = get_smtp_config(Config.DB_PATH)
        cfg['password'] = '••••••••' if cfg['password'] else ''   # mask in GET
        return jsonify({'success': True, 'smtp': cfg})

    data = request.get_json(silent=True) or {}
    cfg  = {
        'host':       data.get('host', '').strip(),
        'port':       int(data.get('port', 587)),
        'username':   data.get('username', '').strip(),
        'use_tls':    bool(data.get('use_tls', True)),
        'from_name':  data.get('from_name', 'Trintz Data Labs').strip(),
        'from_email': data.get('from_email', '').strip(),
    }
    # Only update password if a real value was sent (not the masked placeholder)
    pw = data.get('password', '')
    if pw and pw != '••••••••':
        cfg['password'] = pw
    else:
        cfg['password'] = get_smtp_config(Config.DB_PATH)['password']

    save_smtp_config(Config.DB_PATH, cfg)
    audit(Config.DB_PATH, 'SMTP_SETTINGS', 'SMTP configuration updated', ip=request.remote_addr)
    return jsonify({'success': True, 'message': 'SMTP settings saved.'})


# ── Email test ────────────────────────────────────────────────────────────────

@api_bp.route('/smtp/test', methods=['POST'])
def smtp_test():
    err = _require_auth()
    if err:
        return err

    data     = request.get_json(silent=True) or {}
    to_email = data.get('to_email', '').strip()
    if not to_email:
        return jsonify({'success': False, 'error': 'to_email is required.'}), 400

    # Verify Brevo API is configured
    if not Config.BREVO_API_KEY:
        return jsonify({'success': False, 'error': 'BREVO_API_KEY not set in .env'}), 400
    if not Config.BREVO_SENDER_EMAIL:
        return jsonify({'success': False, 'error': 'BREVO_SENDER_EMAIL not set in .env'}), 400

    html = """
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;">
      <div style="background:#4f46e5;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px;">
        <h1 style="color:#fff;margin:0;font-size:20px;">TrintzPOS License Admin</h1>
        <p style="color:#c7d2fe;margin:6px 0 0;">Email Configuration Test</p>
      </div>
      <p style="color:#374151;">Your email settings are configured correctly.</p>
      <p style="color:#374151;">You can now send customer distribution packages directly from the License Admin portal.</p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
      <p style="color:#9ca3af;font-size:12px;text-align:center;">
        &copy; 2025 Trintz Data Labs &nbsp;&middot;&nbsp; support@trintzlabs.com
      </p>
    </div>"""

    from core.email_sender import send_email as _send
    result = _send(
        to_email=to_email,
        subject='TrintzPOS License Admin — Email Test',
        html=html,
        text='Email test from TrintzPOS License Admin — your settings work correctly.',
    )

    if result.get('success'):
        audit(Config.DB_PATH, 'EMAIL_TEST',
              f'Test email sent to {to_email} via Brevo REST API (MCP)',
              ip=request.remote_addr)
        return jsonify({'success': True, 'message': f'Test email sent to {to_email}'})
    return jsonify({'success': False, 'error': result.get('error', 'Unknown error')})
