from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required, permission_required, hash_password
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

store_settings_bp = Blueprint('store_settings', __name__)

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


@store_settings_bp.route('/store-settings', methods=['GET'])
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


@store_settings_bp.route('/store-settings', methods=['POST'])
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
