import os
import sys
import socket

# ── Entry-point guard ──────────────────────────────────────────────────────────
# wsgi.py is for production WSGI hosts (gunicorn, uWSGI).
# For development, always use:  python app.py
# Running wsgi.py AND app.py at the same time will cause a port conflict.

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(__file__))

# Minimal startup logging
port = os.environ.get('PORT', '5001')
print(f"Starting POS application on port {port}")

from app import create_app

# Create the Flask application
application = create_app()

# Initialize the database
try:
    with application.app_context():
        from db import init_db
        init_db()
        print("Database initialized successfully!")
except Exception as e:
    print(f"Error initializing database: {e}")

# Start the backup scheduler (gunicorn --preload runs this once in the master
# process before forking workers, so only one scheduler instance is created).
try:
    from backup_scheduler import init_scheduler
    init_scheduler(application)
    print("Backup scheduler started.")
except Exception as e:
    print(f"Backup scheduler failed to start: {e}")

print("Application ready!")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        if _s.connect_ex(('127.0.0.1', port)) == 0:
            print(f"\n[ERROR] Port {port} is already in use — use app.py as the single entry point.\n")
            sys.exit(1)
    application.run(host="0.0.0.0", port=port, debug=False)