from flask import Blueprint, request, jsonify
from db import get_db_connection, release_db_connection
from auth import admin_required
from psycopg2.extras import RealDictCursor
import os
import shutil
import datetime
import platform
import re
from ._helpers import _apply_restore_sql, _split_sql_statements
service_backup_bp = Blueprint('service_backup', __name__)

@service_backup_bp.route('/admin/service/backup', methods=['POST', 'OPTIONS'])
@admin_required
def create_backup(payload):
    """Delegate to backup_engine — produces .sql.gz and logs to backup_logs."""
    from backup_engine import run_backup
    try:
        result = run_backup(backup_type='manual')
        conn = get_db_connection()
        cur  = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO backup_logs
                    (filename, file_size_bytes, backup_type, destination, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (result['filename'], result['size_bytes'], 'manual', 'local', 'success'))
            log_id = cur.fetchone()[0]
            conn.commit()
        finally:
            cur.close()
            release_db_connection(conn)
        return jsonify({
            'success': True,
            'message': f'Backup created: {result["filename"]}',
            'backup_file': result['filename'],
            'file_size': result['size_bytes'],
            'log_id': log_id,
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@service_backup_bp.route('/admin/service/backups', methods=['GET'])
@admin_required
def list_backups(payload):
    """Return all backups from backup_logs (covers both backup.html and service.html runs)."""
    import os as _os
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT id, filename, file_size_bytes, backup_type, destination,
                   status, created_at
            FROM backup_logs
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
        backups = []
        for row in rows:
            log_id, fname, size, btype, dest, status, created_at = row
            fp = _os.path.join(BACKUP_DIR, fname)
            backups.append({
                'id':       log_id,
                'filename': fname,
                'size':     size or 0,
                'created':  created_at.isoformat() if created_at else '',
                'type':     btype,
                'dest':     dest,
                'status':   status,
                'exists':   _os.path.isfile(fp),
            })
        return jsonify({'success': True, 'backups': backups, 'count': len(backups)}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@service_backup_bp.route('/admin/service/backups/<int:log_id>', methods=['DELETE'])
@admin_required
def delete_backup(payload, log_id):
    """Delete backup file + log entry by log_id."""
    import os as _os
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Backup not found'}), 404
        fp = _os.path.join(BACKUP_DIR, row[0])
        if _os.path.isfile(fp):
            _os.remove(fp)
        cur.execute('DELETE FROM backup_logs WHERE id = %s', (log_id,))
        conn.commit()
        return jsonify({'success': True, 'message': f'Deleted: {row[0]}'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@service_backup_bp.route('/admin/service/restore', methods=['POST'])
@admin_required
def restore_backup(payload):
    """Restore from a backup file (handles both .sql and .sql.gz). Accepts log_id or filename."""
    import os as _os
    import gzip as _gzip
    from backup_engine import BACKUP_DIR
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        data     = request.get_json() or {}
        log_id   = data.get('log_id')
        filename = data.get('backup_file')

        if log_id:
            cur2 = conn.cursor()
            cur2.execute('SELECT filename FROM backup_logs WHERE id = %s', (log_id,))
            row = cur2.fetchone()
            cur2.close()
            if not row:
                return jsonify({'success': False, 'message': 'Backup log not found'}), 404
            filename = row[0]

        if not filename:
            return jsonify({'success': False, 'message': 'No backup specified'}), 400

        backup_path = _os.path.join(BACKUP_DIR, filename)
        # Path traversal guard
        if not _os.path.abspath(backup_path).startswith(_os.path.abspath(BACKUP_DIR)):
            return jsonify({'success': False, 'message': 'Invalid filename'}), 400
        if not _os.path.isfile(backup_path):
            return jsonify({'success': False, 'message': f'File not found: {filename}'}), 404

        # Read — supports both plain .sql and gzip .sql.gz
        if filename.endswith('.gz'):
            with _gzip.open(backup_path, 'rt', encoding='utf-8') as f:
                sql_content = f.read()
        else:
            with open(backup_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()

        # Use the shared applier (clears tables first, then inserts) so a restore
        # onto a populated DB replaces data instead of failing on duplicate keys.
        ok, err = _apply_restore_sql(conn, sql_content)
        return jsonify({
            'success': True,
            'message': f'Restored from {filename} — {ok} statements applied, {err} skipped'
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# Restore order: parents before children (FK-safe for inserts). Reverse for
# the pre-clear delete pass so children are removed before parents.
@service_backup_bp.route('/admin/service/restore-upload', methods=['POST'])
@admin_required
def restore_backup_upload(payload):
    """
    Restore from a browsed/uploaded backup file (multipart 'file').
    Accepts a .sql or .sql.gz dump — useful for restoring a backup that is not
    in the server's backup history (e.g. downloaded earlier or from another host).
    """
    import gzip as _gzip
    import io as _io

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400

    fname = f.filename
    if not (fname.endswith('.sql') or fname.endswith('.sql.gz') or fname.endswith('.gz')):
        return jsonify({'success': False,
                        'message': 'Invalid file type — upload a .sql or .sql.gz backup'}), 400

    try:
        raw = f.read()
        if not raw:
            return jsonify({'success': False, 'message': 'Uploaded file is empty'}), 400
        # Decode — gzip if compressed, else plain UTF-8
        if fname.endswith('.gz'):
            try:
                sql_content = _gzip.GzipFile(fileobj=_io.BytesIO(raw)).read().decode('utf-8')
            except OSError:
                return jsonify({'success': False,
                                'message': 'File is not a valid gzip archive'}), 400
        else:
            sql_content = raw.decode('utf-8', errors='replace')

        if not sql_content.strip():
            return jsonify({'success': False, 'message': 'Backup file contains no SQL'}), 400

        conn = get_db_connection()
        try:
            ok, err = _apply_restore_sql(conn, sql_content)
        finally:
            release_db_connection(conn)

        return jsonify({
            'success': True,
            'message': f'Restored from uploaded {fname} — {ok} statements applied, {err} skipped'
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
