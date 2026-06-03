"""
run.py — Start the TrintzPOS License Admin Portal.

    python run.py

Binds to 127.0.0.1 only. Never accessible from the network.
"""

import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Startup checks ─────────────────────────────────────────────────────────────

priv_path = os.environ.get('PRIVATE_KEY_PATH', 'keys/private.pem')
if not Path(priv_path).exists():
    print(f"\n  [WARN] Private key not found at: {priv_path}")
    print("  License issuance will be unavailable until you add keys/private.pem")
    print("  Generate a key pair at http://127.0.0.1:5002/settings after starting.\n")

secret = os.environ.get('SECRET_KEY', '')
if not secret or secret == 'change-me-to-a-long-random-string':
    print("\n  [WARN] SECRET_KEY is not set. Copy .env.example to .env and set a strong value.")
    print("  Generate: python -c \"import secrets; print(secrets.token_hex(32))\"\n")

# ── Launch ─────────────────────────────────────────────────────────────────────

from app import create_app

flask_app = create_app()
port      = int(os.environ.get('PORT', 5002))

print(f"\n  ╔══════════════════════════════════════════════╗")
print(f"  ║   TrintzPOS  License Admin Portal            ║")
print(f"  ║   http://127.0.0.1:{port}                      ║")
print(f"  ║   Localhost only — not network accessible    ║")
print(f"  ╚══════════════════════════════════════════════╝\n")

flask_app.run(host='127.0.0.1', port=port, debug=False)
