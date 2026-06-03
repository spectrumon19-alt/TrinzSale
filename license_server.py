"""
TrintzPOS License Server
Deploy this on any VPS/cloud (Render, Railway, Heroku, etc.) as a separate app.
It manages license issuance, activation tracking, and online validation.

Usage:
    pip install flask cryptography
    python license_server.py

Environment variables:
    PORT              — HTTP port (default 5050)
    ADMIN_API_KEY     — Secret for admin endpoints (required in production)
    DATABASE_URL      — Optional; if set, uses PostgreSQL instead of SQLite
"""

import os
import json
import sqlite3
import hashlib
import secrets
import base64
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify
from cryptography.fernet import Fernet

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

DB_PATH = os.environ.get("LICENSE_DB", "licenses.db")
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "change-me-in-production")

MASTER_KEY_FILE = "server_master.key"

def _get_or_create_master_key() -> bytes:
    if os.path.exists(MASTER_KEY_FILE):
        return open(MASTER_KEY_FILE, "rb").read()
    key = Fernet.generate_key()
    with open(MASTER_KEY_FILE, "wb") as f:
        f.write(key)
    print(f"[INIT] Generated new master key → {MASTER_KEY_FILE}")
    print("[WARN] Back up this file securely!")
    return key

MASTER_KEY = _get_or_create_master_key()
cipher = Fernet(MASTER_KEY)


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS licenses (
            id              TEXT PRIMARY KEY,
            license_type    TEXT NOT NULL DEFAULT 'Standard',
            created_at      TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            hardware_bound  INTEGER NOT NULL DEFAULT 0,
            activated       INTEGER NOT NULL DEFAULT 0,
            activated_at    TEXT,
            fingerprint     TEXT,
            revoked         INTEGER NOT NULL DEFAULT 0,
            notes           TEXT
        );
        """)
    print(f"[DB] Initialized → {DB_PATH}")


# ── Auth decorator ─────────────────────────────────────────────────────────────

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key") or request.args.get("admin_key")
        if key != ADMIN_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ── License key encode/decode ──────────────────────────────────────────────────

def encode_license(payload: dict) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(cipher.encrypt(raw)).decode()


def decode_license(token: str) -> dict | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        return json.loads(cipher.decrypt(raw))
    except Exception:
        return None


# ── Admin: Generate licenses ───────────────────────────────────────────────────

@app.route("/admin/generate", methods=["POST"])
@require_admin
def admin_generate():
    """
    Generate one or more license keys.
    Body JSON: { count, days, license_type, hardware_bound }
    """
    data = request.get_json(silent=True) or {}
    count = min(int(data.get("count", 1)), 500)
    days = int(data.get("days", 365))
    license_type = data.get("license_type", "Standard")
    hardware_bound = bool(data.get("hardware_bound", True))

    now = datetime.utcnow()
    expires_at = now + timedelta(days=days)
    keys = []

    with get_db() as conn:
        for _ in range(count):
            lid = secrets.token_urlsafe(16)
            payload = {
                "license_id": lid,
                "license_type": license_type,
                "creation_date": now.isoformat(),
                "expiry_date": expires_at.isoformat(),
                "hardware_binding": hardware_bound,
                "machine_id": None,
                "activated": False,
                "activation_date": None,
            }
            token = encode_license(payload)
            conn.execute(
                """INSERT INTO licenses (id, license_type, created_at, expires_at,
                   hardware_bound) VALUES (?,?,?,?,?)""",
                (lid, license_type, now.isoformat(), expires_at.isoformat(),
                 1 if hardware_bound else 0)
            )
            keys.append({"license_id": lid, "license_key": token,
                         "expires_at": expires_at.isoformat()})

    return jsonify({"generated": count, "licenses": keys}), 201


# ── Admin: List licenses ───────────────────────────────────────────────────────

@app.route("/admin/licenses", methods=["GET"])
@require_admin
def admin_list():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


# ── Admin: Revoke license ──────────────────────────────────────────────────────

@app.route("/admin/revoke/<license_id>", methods=["POST"])
@require_admin
def admin_revoke(license_id):
    with get_db() as conn:
        conn.execute("UPDATE licenses SET revoked=1 WHERE id=?", (license_id,))
    return jsonify({"revoked": license_id})


# ── Client: Validate license ───────────────────────────────────────────────────

@app.route("/api/validate", methods=["POST"])
def api_validate():
    """
    Client calls this to validate (and optionally activate) a license.
    Body JSON: { license_key, fingerprint }
    """
    data = request.get_json(silent=True) or {}
    token = data.get("license_key", "").strip()
    fingerprint = data.get("fingerprint", "").strip()

    if not token:
        return jsonify({"valid": False, "message": "license_key required"}), 400

    payload = decode_license(token)
    if payload is None:
        return jsonify({"valid": False, "message": "Invalid license key"}), 400

    lid = payload.get("license_id")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM licenses WHERE id=?", (lid,)).fetchone()

    if row is None:
        return jsonify({"valid": False, "message": "License not found"}), 404

    if row["revoked"]:
        return jsonify({"valid": False, "message": "License has been revoked"}), 403

    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.utcnow() > expires_at:
        return jsonify({"valid": False, "message": "License has expired"}), 402

    # Hardware binding
    if row["hardware_bound"] and row["activated"] and row["fingerprint"]:
        if row["fingerprint"] != fingerprint:
            return jsonify({"valid": False, "message": "License bound to a different machine"}), 403

    # First activation
    if not row["activated"] and fingerprint:
        with get_db() as conn:
            conn.execute(
                "UPDATE licenses SET activated=1, activated_at=?, fingerprint=? WHERE id=?",
                (datetime.utcnow().isoformat(), fingerprint, lid)
            )

    days_left = max(0, (expires_at - datetime.utcnow()).days)
    return jsonify({
        "valid": True,
        "license_type": row["license_type"],
        "days_remaining": days_left,
        "expiry_date": row["expires_at"],
    })


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5050))
    print(f"[START] TrintzPOS License Server on port {port}")
    if ADMIN_KEY == "change-me-in-production":
        print("[WARN] Set ADMIN_API_KEY env variable before deploying!")
    app.run(host="0.0.0.0", port=port, debug=False)
