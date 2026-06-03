from flask import Blueprint, request, jsonify, send_file, Response
from db import get_db_connection, release_db_connection
from auth import token_required
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime

backup_bp = Blueprint('backup', __name__)

def _app_base() -> str:
    base = os.environ.get('TRINTZ_APP_BASE')
    if base:
        return base
    f = __file__
    if '.zip' in f.replace('\\', '/'):
        idx = f.lower().find('.zip')
        return os.path.dirname(f[:idx + 4])
    return os.path.dirname(os.path.dirname(os.path.abspath(f)))

BACKUP_DIR = os.path.join(_app_base(), 'backups')


def _admin_only(payload):
    return payload.get('role') in ('Admin', 'Super Admin', 'Manager')


# ── Manual backup trigger ─────────────────────────────────────────────────────

@backup_bp.route('/backup/run', methods=['POST'])
@token_required
def run_backup_now(payload):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    from backup_engine import run_backup, upload_to_gdrive, get_backup_settings

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        result        = run_backup(backup_type='manual')
        settings      = get_backup_settings()
        gdrive_id     = None
        error_msg     = None
        destination   = 'local'

        if settings.get('gdrive_enabled') and settings.get('gdrive_credentials'):
            try:
                gdrive_id   = upload_to_gdrive(
                    result['filepath'],
                    settings.get('gdrive_folder_id', ''),
                    settings['gdrive_credentials']
                )
                destination = 'gdrive'
            except Exception as e:
                error_msg = str(e)

        cur.execute("""
            INSERT INTO backup_logs
                (filename, file_size_bytes, backup_type, destination, status, error_message, gdrive_file_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            result['filename'], result['size_bytes'], 'manual',
            destination, 'success' if not error_msg else 'partial',
            error_msg, gdrive_id
        ))
        log_id = cur.fetchone()[0]
        conn.commit()

        return jsonify({
            'success': True,
            'filename':    result['filename'],
            'size_bytes':  result['size_bytes'],
            'destination': destination,
            'gdrive_id':   gdrive_id,
            'log_id':      log_id,
            'error':       error_msg
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── Backup history ────────────────────────────────────────────────────────────

@backup_bp.route('/backup/list', methods=['GET'])
@token_required
def list_backups(payload):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, filename, file_size_bytes, backup_type, destination,
                   status, error_message, gdrive_file_id, created_at
            FROM backup_logs
            ORDER BY created_at DESC
            LIMIT 50
        """)
        logs = cur.fetchall()

        # Annotate with local file existence
        result = []
        for row in logs:
            d = dict(row)
            fp = os.path.join(BACKUP_DIR, d['filename'])
            d['local_exists'] = os.path.isfile(fp)
            d['created_at']   = d['created_at'].isoformat() if d['created_at'] else None
            result.append(d)

        return jsonify(result)
    finally:
        cur.close()
        release_db_connection(conn)


# ── Download backup file ──────────────────────────────────────────────────────

@backup_bp.route('/backup/download/<int:log_id>', methods=['GET'])
@token_required
def download_backup(payload, log_id):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Backup not found'}), 404

        fp = os.path.join(BACKUP_DIR, row['filename'])
        if not os.path.isfile(fp):
            return jsonify({'error': 'File not on local disk (may only exist on Google Drive)'}), 404

        return send_file(fp, as_attachment=True, download_name=row['filename'],
                         mimetype='application/gzip')
    finally:
        cur.close()
        release_db_connection(conn)


# ── Delete local backup file ──────────────────────────────────────────────────

@backup_bp.route('/backup/<int:log_id>', methods=['DELETE'])
@token_required
def delete_backup(payload, log_id):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404

        fp = os.path.join(BACKUP_DIR, row['filename'])
        if os.path.isfile(fp):
            os.remove(fp)

        cur.execute('DELETE FROM backup_logs WHERE id = %s', (log_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── Settings ──────────────────────────────────────────────────────────────────

@backup_bp.route('/backup/settings', methods=['GET'])
@token_required
def get_settings(payload):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    from backup_engine import get_backup_settings
    s = get_backup_settings()
    # Never send the raw credentials to the client
    s.pop('gdrive_credentials', None)
    s['gdrive_configured'] = bool(s.get('gdrive_credentials') or _load_creds_from_db())
    return jsonify(s)


@backup_bp.route('/backup/settings', methods=['POST'])
@token_required
def save_settings(payload):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json() or {}

    enabled        = bool(data.get('enabled', False))
    schedule_time  = data.get('schedule_time', '02:00')
    retention_days = int(data.get('retention_days', 30))
    gdrive_enabled = bool(data.get('gdrive_enabled', False))
    gdrive_folder  = data.get('gdrive_folder_id', '')
    gdrive_creds   = data.get('gdrive_credentials', None)   # only present when re-uploading

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute('SELECT id FROM backup_settings LIMIT 1')
        existing = cur.fetchone()

        if existing:
            if gdrive_creds:
                cur.execute("""
                    UPDATE backup_settings SET
                        enabled=%s, schedule_time=%s, retention_days=%s,
                        gdrive_enabled=%s, gdrive_folder_id=%s, gdrive_credentials=%s,
                        updated_at=NOW()
                    WHERE id=%s
                """, (enabled, schedule_time, retention_days, gdrive_enabled,
                      gdrive_folder, gdrive_creds, existing[0]))
            else:
                cur.execute("""
                    UPDATE backup_settings SET
                        enabled=%s, schedule_time=%s, retention_days=%s,
                        gdrive_enabled=%s, gdrive_folder_id=%s, updated_at=NOW()
                    WHERE id=%s
                """, (enabled, schedule_time, retention_days,
                      gdrive_enabled, gdrive_folder, existing[0]))
        else:
            cur.execute("""
                INSERT INTO backup_settings
                    (enabled, schedule_time, retention_days, gdrive_enabled,
                     gdrive_folder_id, gdrive_credentials)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (enabled, schedule_time, retention_days,
                  gdrive_enabled, gdrive_folder, gdrive_creds or ''))

        conn.commit()

        # Update scheduler trigger if time changed
        try:
            from backup_scheduler import reschedule
            reschedule(schedule_time)
        except Exception:
            pass

        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


def _load_creds_from_db():
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute('SELECT gdrive_credentials FROM backup_settings LIMIT 1')
        row = cur.fetchone()
        return row[0] if row else ''
    finally:
        cur.close()
        release_db_connection(conn)


# ── Test Google Drive connection ──────────────────────────────────────────────

@backup_bp.route('/backup/gdrive/test', methods=['POST'])
@token_required
def test_gdrive(payload):
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    creds_json = request.get_json(force=True).get('credentials_json', '')
    if not creds_json:
        creds_json = _load_creds_from_db()
    if not creds_json:
        return jsonify({'error': 'No credentials configured'}), 400

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        info  = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        svc = build('drive', 'v3', credentials=creds, cache_discovery=False)
        about = svc.about().get(fields='user').execute()
        return jsonify({'success': True, 'account': about.get('user', {}).get('emailAddress', 'connected')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
