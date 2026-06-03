"""
SQLite database layer — all license records and audit log.
"""

import sqlite3
import json
from datetime import date, datetime
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    serial           TEXT UNIQUE NOT NULL,
    customer         TEXT NOT NULL,
    email            TEXT NOT NULL,
    license_type     TEXT NOT NULL DEFAULT 'Professional',
    expiry_date      TEXT NOT NULL,
    hardware_binding INTEGER NOT NULL DEFAULT 0,
    machine_id       TEXT,
    max_users        INTEGER NOT NULL DEFAULT 5,
    features         TEXT NOT NULL DEFAULT '[]',
    issued_at        TEXT NOT NULL,
    issued_by        TEXT NOT NULL DEFAULT 'admin',
    full_key         TEXT NOT NULL,
    notes            TEXT,
    revoked_at       TEXT,
    revoked_reason   TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    action    TEXT NOT NULL,
    detail    TEXT,
    admin     TEXT DEFAULT 'admin',
    ip        TEXT,
    ts        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    conn = _connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── Status helper (computed, not stored) ──────────────────────────────────────

def _compute_status(row: sqlite3.Row) -> str:
    if row['revoked_at']:
        return 'revoked'
    try:
        exp = date.fromisoformat(row['expiry_date'][:10])
    except ValueError:
        return 'unknown'
    today = date.today()
    if exp < today:
        return 'expired'
    if (exp - today).days <= 30:
        return 'expiring'
    return 'active'


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d['features'] = json.loads(d.get('features') or '[]')
    d['status']   = _compute_status(row)
    try:
        exp = date.fromisoformat(d['expiry_date'][:10])
        d['days_remaining'] = max(0, (exp - date.today()).days)
    except ValueError:
        d['days_remaining'] = 0
    return d


# ── Queries ───────────────────────────────────────────────────────────────────

def get_stats(db_path: str) -> dict:
    conn = _connect(db_path)
    rows = [_row_to_dict(r) for r in conn.execute("SELECT * FROM licenses").fetchall()]
    conn.close()
    total    = len(rows)
    active   = sum(1 for r in rows if r['status'] == 'active')
    expiring = sum(1 for r in rows if r['status'] == 'expiring')
    expired  = sum(1 for r in rows if r['status'] in ('expired', 'revoked'))
    return {'total': total, 'active': active, 'expiring': expiring, 'expired': expired}


def get_recent_licenses(db_path: str, limit: int = 8) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM licenses ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_all_licenses(db_path: str, status_filter: str = 'all', search: str = '') -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM licenses ORDER BY id DESC"
    ).fetchall()
    conn.close()
    result = [_row_to_dict(r) for r in rows]

    if search:
        q = search.lower()
        result = [r for r in result if q in r['customer'].lower()
                  or q in r['email'].lower()
                  or q in r['serial'].lower()]

    if status_filter != 'all':
        result = [r for r in result if r['status'] == status_filter]

    return result


def get_license(db_path: str, serial: str) -> dict | None:
    conn = _connect(db_path)
    row = conn.execute("SELECT * FROM licenses WHERE serial = ?", (serial,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def insert_license(db_path: str, data: dict) -> None:
    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO licenses
            (serial, customer, email, license_type, expiry_date, hardware_binding,
             machine_id, max_users, features, issued_at, issued_by, full_key, notes)
        VALUES
            (:serial, :customer, :email, :license_type, :expiry_date, :hardware_binding,
             :machine_id, :max_users, :features, :issued_at, :issued_by, :full_key, :notes)
    """, {**data, 'features': json.dumps(data.get('features', []))})
    conn.commit()
    conn.close()


def revoke_license(db_path: str, serial: str, reason: str = '') -> bool:
    conn = _connect(db_path)
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "UPDATE licenses SET revoked_at=?, revoked_reason=? WHERE serial=? AND revoked_at IS NULL",
        (now, reason, serial)
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def audit(db_path: str, action: str, detail: str = '', ip: str = '') -> None:
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO audit_log (action, detail, ip) VALUES (?, ?, ?)",
        (action, detail, ip)
    )
    conn.commit()
    conn.close()


def get_audit_log(db_path: str, limit: int = 50) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Settings (key-value store) ────────────────────────────────────────────────

_SMTP_KEYS = ('smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
              'smtp_tls', 'smtp_from_name', 'smtp_from_email')


def get_setting(db_path: str, key: str, default: str = '') -> str:
    conn = _connect(db_path)
    row  = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(db_path: str, key: str, value: str) -> None:
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_smtp_config(db_path: str) -> dict:
    """
    Return SMTP configuration.

    Source of truth is the .env file (read via Config, which derives Brevo
    credentials automatically). Any value saved in the DB settings table
    overrides the corresponding .env value, so the UI remains optional.
    """
    from config import Config

    def _ov(db_key, env_val):
        # DB value wins if present, else fall back to the .env-derived value
        v = get_setting(db_path, db_key)
        return v if v else env_val

    port_raw = _ov('smtp_port', str(Config.SMTP_PORT))
    tls_raw  = _ov('smtp_tls',  'true' if Config.SMTP_USE_TLS else 'false')

    return {
        'host':       _ov('smtp_host',       Config.SMTP_HOST),
        'port':       int(port_raw or 587),
        'username':   _ov('smtp_user',       Config.SMTP_USER),
        'password':   _ov('smtp_password',   Config.SMTP_PASSWORD),
        'use_tls':    str(tls_raw).lower() != 'false',
        'from_name':  _ov('smtp_from_name',  Config.SMTP_FROM_NAME),
        'from_email': _ov('smtp_from_email', Config.SMTP_FROM_EMAIL or Config.SMTP_USER),
    }


def save_smtp_config(db_path: str, cfg: dict) -> None:
    mapping = {
        'smtp_host':       str(cfg.get('host', '')),
        'smtp_port':       str(cfg.get('port', '587')),
        'smtp_user':       str(cfg.get('username', '')),
        'smtp_password':   str(cfg.get('password', '')),
        'smtp_tls':        'true' if cfg.get('use_tls', True) else 'false',
        'smtp_from_name':  str(cfg.get('from_name', 'Trintz Data Labs')),
        'smtp_from_email': str(cfg.get('from_email', '')),
    }
    for k, v in mapping.items():
        set_setting(db_path, k, v)
