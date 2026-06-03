"""
TrintzPOS Customer Launcher
Build 2026-05-31 | Python 3.13.2
(c) 2025 Trintz Data Labs. Proprietary and confidential.
"""
import os, sys, socket
from dotenv import load_dotenv

load_dotenv()

_base = os.path.dirname(os.path.abspath(__file__))
os.environ["TRINTZ_APP_BASE"] = _base   # routes resolve tmp dirs via this
sys.path.insert(0, os.path.join(_base, "app_code.zip"))
sys.path.insert(1, _base)

_port = int(os.environ.get("PORT", 5001))
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
    if _s.connect_ex(("127.0.0.1", _port)) == 0:
        print(f"[ERROR] Port {_port} is already in use.")
        raise SystemExit(1)

from app import create_app
from backup_scheduler import init_scheduler

_app = create_app()
init_scheduler(_app)
_app.run(host="0.0.0.0", port=_port, debug=False)
