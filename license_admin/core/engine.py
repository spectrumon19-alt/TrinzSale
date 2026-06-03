"""
License Engine — standalone RSA-2048 signing and verification.
No dependency on the main TrintzPOS application.
"""

import json
import base64
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# ── Key management ─────────────────────────────────────────────────────────────

def generate_keypair(private_path: str, public_path: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    Path(private_path).parent.mkdir(parents=True, exist_ok=True)
    Path(private_path).write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    Path(public_path).write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def load_private_key(path: str):
    with open(path, 'rb') as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def load_public_key(path: str):
    with open(path, 'rb') as f:
        return serialization.load_pem_public_key(f.read())


def public_key_fingerprint(path: str) -> str:
    """Return SHA-256 fingerprint of the public key (hex, colon-separated)."""
    pub = load_public_key(path)
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    from cryptography.hazmat.primitives import hashes as _h
    from cryptography.hazmat.backends import default_backend
    digest = _h.Hash(_h.SHA256(), backend=default_backend())
    digest.update(der)
    raw = digest.finalize().hex()
    return ':'.join(raw[i:i+2] for i in range(0, len(raw), 2))


# ── License issuance ───────────────────────────────────────────────────────────

def issue_license(private_key_path: str, payload: dict) -> str:
    """
    Sign the payload dict with the RSA private key.
    Returns the license key string: BASE64URL(json).BASE64URL(signature)
    """
    key = load_private_key(private_key_path)
    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    payload_b64  = base64.urlsafe_b64encode(payload_json.encode()).decode()
    sig = key.sign(
        payload_b64.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.urlsafe_b64encode(sig).decode()
    return f"{payload_b64}.{sig_b64}"


def verify_license(public_key_path: str, license_key: str) -> dict | None:
    """
    Verify the RSA signature and decode the payload.
    Returns the payload dict if valid, None if invalid/tampered.
    """
    parts = license_key.strip().split('.')
    if len(parts) != 2:
        return None
    payload_b64, sig_b64 = parts
    try:
        pub = load_public_key(public_key_path)
        sig = base64.urlsafe_b64decode(sig_b64 + '==')
        pub.verify(
            sig,
            payload_b64.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        payload_json = base64.urlsafe_b64decode(payload_b64 + '==').decode()
        return json.loads(payload_json)
    except Exception:
        return None


def next_serial(db_conn, year: int | None = None) -> str:
    year = year or date.today().year
    row = db_conn.execute(
        "SELECT COUNT(*) FROM licenses WHERE serial LIKE ?",
        (f'TDL-{year}-%',)
    ).fetchone()
    n = (row[0] or 0) + 1
    return f"TDL-{year}-{n:04d}"
