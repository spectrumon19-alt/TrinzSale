import os
import sys
import socket

# ── Entry-point guard ──────────────────────────────────────────────────────────
# This file is a production (waitress) wrapper. For development, use app.py.
# Both start the same Flask app on the same port — running both simultaneously
# will cause a port conflict.  Always use ONE entry point at a time.

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        if _s.connect_ex(('127.0.0.1', port)) == 0:
            print(f"\n[ERROR] Port {port} is already in use.")
            print("  Stop the existing server first (app.py or any other process).\n")
            sys.exit(1)

    from waitress import serve
    from app import create_app
    app = create_app()
    print(f"[serve.py] Starting via waitress on port {port} ...")
    serve(app, host='0.0.0.0', port=port)