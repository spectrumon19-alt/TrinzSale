"""
backup_engine.py — Pure-Python PostgreSQL backup using SELECT queries.
No pg_dump required. Produces a gzip-compressed SQL file with INSERT statements.
Optionally uploads to Google Drive via a service account JSON.
"""

import os
import gzip
import json
import psycopg2
from datetime import datetime

BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'backups')

# Tables to back up in dependency order (parents before children)
BACKUP_TABLES = [
    'users', 'products', 'inventory', 'suppliers',
    'purchase_orders', 'purchase_order_items',
    'sales_invoices', 'sales_invoice_items',
    'sales_returns', 'sales_return_items',
    'supplier_transactions', 'credit_customers', 'credit_transactions',
    'licenses', 'login_activity', 'user_permissions',
    'store_settings', 'backup_settings', 'backup_logs',
]


def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _escape_val(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def run_backup(backup_type='manual'):
    """
    Dump all tables to a gzip SQL file in the backups/ folder.
    Returns dict with filename, path, size_bytes.
    """
    _ensure_backup_dir()

    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'trintzpos_backup_{ts}.sql.gz'
    filepath = os.path.join(BACKUP_DIR, filename)

    from db import get_db_connection, release_db_connection
    conn = get_db_connection()
    cur  = conn.cursor()

    try:
        with gzip.open(filepath, 'wt', encoding='utf-8') as f:
            f.write(f'-- TrintzPOS Database Backup\n')
            f.write(f'-- Generated : {datetime.now().isoformat()}\n')
            f.write(f'-- Type      : {backup_type}\n\n')
            f.write('SET client_encoding = \'UTF8\';\n')
            f.write('SET standard_conforming_strings = on;\n\n')

            # Discover actual tables present in DB
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            existing = {r[0] for r in cur.fetchall()}

            for table in BACKUP_TABLES:
                if table not in existing:
                    continue
                cur.execute(f'SELECT * FROM "{table}"')
                rows = cur.fetchall()
                if not rows:
                    continue
                cols = [desc[0] for desc in cur.description]
                cols_sql = ', '.join(f'"{c}"' for c in cols)

                f.write(f'-- {table}\n')
                for row in rows:
                    vals = ', '.join(_escape_val(v) for v in row)
                    f.write(f'INSERT INTO "{table}" ({cols_sql}) VALUES ({vals});\n')
                f.write('\n')

        size = os.path.getsize(filepath)
        return {'filename': filename, 'filepath': filepath, 'size_bytes': size}

    finally:
        cur.close()
        release_db_connection(conn)


def upload_to_gdrive(filepath, folder_id, credentials_json_str):
    """
    Upload a file to Google Drive using a service account.
    credentials_json_str — the full contents of the service account JSON key file.
    folder_id           — Google Drive folder ID to upload into (leave blank for root).
    Returns the Drive file ID on success.
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise RuntimeError('Google Drive packages not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib')

    info  = json.loads(credentials_json_str)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/drive.file']
    )
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)

    meta = {'name': os.path.basename(filepath)}
    if folder_id and folder_id.strip():
        meta['parents'] = [folder_id.strip()]

    media  = MediaFileUpload(filepath, mimetype='application/gzip', resumable=True)
    result = service.files().create(body=meta, media_body=media, fields='id').execute()
    return result.get('id')


def delete_old_backups(retention_days=30):
    """Remove local backup files older than retention_days."""
    _ensure_backup_dir()
    cutoff = datetime.now().timestamp() - retention_days * 86400
    removed = []
    for fn in os.listdir(BACKUP_DIR):
        fp = os.path.join(BACKUP_DIR, fn)
        if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
            os.remove(fp)
            removed.append(fn)
    return removed


def get_backup_settings():
    """Read backup settings from DB. Returns dict."""
    from db import get_db_connection, release_db_connection
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute('SELECT * FROM backup_settings ORDER BY id LIMIT 1')
        row = cur.fetchone()
        if not row:
            return {
                'enabled': False, 'schedule_time': '02:00',
                'retention_days': 30, 'gdrive_enabled': False,
                'gdrive_folder_id': '', 'gdrive_credentials': ''
            }
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        cur.close()
        release_db_connection(conn)
