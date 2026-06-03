import os
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, session
from config import Config
from core.db import get_stats, get_recent_licenses, get_all_licenses, get_audit_log

pages_bp = Blueprint('pages', __name__)


def _check_password(plain: str) -> bool:
    stored = Config.ADMIN_PASSWORD
    if stored.startswith('$2b$') or stored.startswith('$2a$'):
        import bcrypt
        return bcrypt.checkpw(plain.encode(), stored.encode())
    return plain == stored


@pages_bp.route('/')
def index():
    return redirect(url_for('pages.dashboard'))


@pages_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('admin'):
        return redirect(url_for('pages.dashboard'))
    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if _check_password(pw):
            session['admin'] = True
            session.permanent = True
            return redirect(url_for('pages.dashboard'))
        error = 'Incorrect password. Please try again.'
    return render_template('login.html', error=error)


@pages_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('pages.login'))


@pages_bp.route('/dashboard')
def dashboard():
    stats      = get_stats(Config.DB_PATH)
    recent     = get_recent_licenses(Config.DB_PATH, limit=8)
    key_exists = Path(Config.PRIVATE_KEY_PATH).exists()
    return render_template('dashboard.html', stats=stats, recent=recent, key_exists=key_exists)


@pages_bp.route('/licenses')
def licenses():
    status_filter = request.args.get('status', 'all')
    search        = request.args.get('q', '').strip()
    rows          = get_all_licenses(Config.DB_PATH, status_filter=status_filter, search=search)
    stats         = get_stats(Config.DB_PATH)
    return render_template('licenses.html', licenses=rows, status_filter=status_filter,
                           search=search, stats=stats)


@pages_bp.route('/settings')
def settings():
    priv_exists = Path(Config.PRIVATE_KEY_PATH).exists()
    pub_exists  = Path(Config.PUBLIC_KEY_PATH).exists()
    fp = ''
    if pub_exists:
        try:
            from core.engine import public_key_fingerprint
            fp = public_key_fingerprint(Config.PUBLIC_KEY_PATH)
        except Exception:
            fp = 'Error reading key'
    log = get_audit_log(Config.DB_PATH, limit=20)
    return render_template('settings.html',
                           priv_exists=priv_exists, pub_exists=pub_exists,
                           priv_path=Config.PRIVATE_KEY_PATH,
                           pub_path=Config.PUBLIC_KEY_PATH,
                           key_fingerprint=fp,
                           audit_log=log)
