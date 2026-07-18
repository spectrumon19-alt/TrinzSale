"""
backup_scheduler.py — APScheduler job that runs the daily DB backup.
Initialized once in app.py using init_scheduler(app).
Uses a file-lock so only one process runs the job in multi-worker (Gunicorn) deployments.
"""

import os
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler = None
_LOCK_FILE = os.path.join(os.path.dirname(__file__), 'backups', '.scheduler.lock')


def _run_scheduled_backup():
    """Called by APScheduler. Runs backup + optional GDrive upload + cleanup."""
    # File-lock: only one process executes (important for Gunicorn multi-worker)
    os.makedirs(os.path.dirname(_LOCK_FILE), exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(_LOCK_FILE, 'w')
        import msvcrt
        try:
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return  # Another worker already running the job
    except Exception:
        pass  # Non-Windows: proceed without lock

    try:
        from backup_engine import run_backup, upload_to_gdrive, delete_old_backups, get_backup_settings
        from db import get_db_connection, release_db_connection

        settings = get_backup_settings()
        if not settings.get('enabled'):
            return

        # Run backup
        result = run_backup(backup_type='scheduled')
        gdrive_file_id = None
        error_msg      = None
        status         = 'success'

        # Upload to Google Drive if configured.
        # OAuth (user's own Google account) is preferred; service-account JSON
        # is the legacy fallback. Mirrors the manual-run logic in routes/backup.py.
        if settings.get('gdrive_enabled'):
            from routes.backup_oauth import get_oauth_tokens, refresh_oauth_token_if_needed
            from backup_engine import upload_to_gdrive_oauth
            oauth_tokens = get_oauth_tokens()
            if oauth_tokens:
                try:
                    access_token = refresh_oauth_token_if_needed()
                    if not access_token:
                        raise Exception('OAuth token expired and could not be refreshed')
                    gdrive_file_id = upload_to_gdrive_oauth(
                        result['filepath'],
                        settings.get('gdrive_folder_id', ''),
                        access_token
                    )
                except Exception as e:
                    error_msg = f'GDrive upload failed (OAuth): {e}'
                    logger.warning(error_msg)
            elif settings.get('gdrive_credentials'):
                try:
                    gdrive_file_id = upload_to_gdrive(
                        result['filepath'],
                        settings.get('gdrive_folder_id', ''),
                        settings['gdrive_credentials']
                    )
                except Exception as e:
                    error_msg = f'GDrive upload failed: {e}'
                    logger.warning(error_msg)

        # Log to DB
        conn = get_db_connection()
        cur  = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO backup_logs
                    (filename, file_size_bytes, backup_type, destination, status, error_message, gdrive_file_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                result['filename'], result['size_bytes'], 'scheduled',
                'gdrive' if gdrive_file_id else 'local',
                status, error_msg, gdrive_file_id
            ))
            conn.commit()
        finally:
            cur.close()
            release_db_connection(conn)

        # Clean up old files
        retention = int(settings.get('retention_days', 30))
        delete_old_backups(retention)

        logger.info(f'[Backup] Scheduled backup complete: {result["filename"]} ({result["size_bytes"]} bytes)')

    except Exception as e:
        logger.error(f'[Backup] Scheduled backup failed: {e}')
    finally:
        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass


def _parse_time(t):
    """Parse HH:MM string into (hour, minute)."""
    try:
        h, m = t.split(':')
        return int(h), int(m)
    except Exception:
        return 2, 0


def init_scheduler(app):
    """Create and start the APScheduler. Call once from app.py."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)

    try:
        from backup_engine import get_backup_settings
        settings = get_backup_settings()
        hour, minute = _parse_time(settings.get('schedule_time', '02:00'))
    except Exception:
        hour, minute = 2, 0

    _scheduler.add_job(
        _run_scheduled_backup,
        trigger=CronTrigger(hour=hour, minute=minute),
        id='daily_backup',
        replace_existing=True,
        misfire_grace_time=3600
    )
    _scheduler.start()
    logger.info(f'[Backup] Scheduler started — daily at {hour:02d}:{minute:02d}')


def reschedule(schedule_time):
    """Update the job trigger after settings change."""
    global _scheduler
    if _scheduler is None:
        return
    hour, minute = _parse_time(schedule_time)
    _scheduler.reschedule_job(
        'daily_backup',
        trigger=CronTrigger(hour=hour, minute=minute)
    )
    logger.info(f'[Backup] Rescheduled to {hour:02d}:{minute:02d}')
