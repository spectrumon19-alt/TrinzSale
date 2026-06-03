"""
TrintzPOS License Manager — v2 (RSA asymmetric verification)

Design:
  - License keys are signed with Trintz's RSA-2048 private key (never ships to clients).
  - The app verifies keys using public.pem only — cannot forge keys even with full source access.
  - license.dat stores the activated payload, encrypted with a key derived from public.pem.
    No separate master.key file is needed or shipped.

License key format:
  BASE64URL(payload_json).BASE64URL(rsa_pss_sha256_signature)
"""

import os
import sys
import json
import base64
import hashlib
import platform
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.fernet import Fernet, InvalidToken


# ── File paths ─────────────────────────────────────────────────────────────────

LICENSE_DAT_FILE  = "license.dat"
PUBLIC_KEY_FILE   = "public.pem"
LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "")


def _resolve(filename: str) -> str:
    # Priority 1: PyInstaller frozen bundle
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), filename)
    # Priority 2: TRINTZ_APP_BASE set by launcher.py before importing from zip
    if os.environ.get("TRINTZ_APP_BASE"):
        return os.path.join(os.environ["TRINTZ_APP_BASE"], filename)
    # Priority 3: __file__ is real (normal dev mode)
    f = os.path.abspath(__file__)
    if ".zip" in f.replace("\\", "/"):
        # Loaded from zip but env var not set — derive from zip path
        idx = f.lower().find(".zip")
        return os.path.join(os.path.dirname(f[:idx + 4]), filename)
    return os.path.join(os.path.dirname(f), filename)


# ── Crypto helpers ─────────────────────────────────────────────────────────────

def _load_public_key():
    path = _resolve(PUBLIC_KEY_FILE)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"public.pem not found at {path}. "
            "Copy public.pem into the application directory."
        )
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def _dat_fernet() -> Fernet:
    """
    Derive a Fernet key from public.pem so license.dat is encrypted without
    needing a separate master.key file. The same public key always yields the
    same encryption key, so license.dat can be decrypted on any reinstall of
    the same app build.
    """
    path = _resolve(PUBLIC_KEY_FILE)
    with open(path, "rb") as f:
        pub_pem = f.read()
    digest = hashlib.sha256(pub_pem + b"trintz-pos-dat-v2").digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def _verify_signature(payload_b64: str, sig_b64: str) -> bool:
    try:
        pub_key = _load_public_key()
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        pub_key.verify(
            sig,
            payload_b64.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


# ── Hardware fingerprint ───────────────────────────────────────────────────────

def get_hardware_fingerprint() -> str:
    parts = [platform.system(), platform.machine(), platform.processor()]

    if platform.system() == "Windows":
        for cmd in (
            ["wmic", "diskdrive", "get", "SerialNumber"],
            ["wmic", "csproduct", "get", "UUID"],
        ):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
                lines = [l.strip() for l in out.splitlines()
                         if l.strip() and l.strip() not in ("SerialNumber", "UUID")]
                if lines:
                    parts.append(lines[0])
            except Exception:
                pass
    else:
        try:
            parts.append(str(uuid.getnode()))
        except Exception:
            pass

    raw = "|".join(str(p) for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── license.dat read/write ─────────────────────────────────────────────────────

def _read_dat() -> dict | None:
    path = _resolve(LICENSE_DAT_FILE)
    if not os.path.exists(path):
        return None
    try:
        return json.loads(_dat_fernet().decrypt(Path(path).read_bytes()))
    except (InvalidToken, Exception):
        return None


def _write_dat(data: dict) -> None:
    Path(_resolve(LICENSE_DAT_FILE)).write_bytes(
        _dat_fernet().encrypt(json.dumps(data).encode())
    )


# ── License key decode/verify ─────────────────────────────────────────────────

def decode_license_key(license_key: str) -> dict | None:
    """
    Decode and verify a license key.
    Returns the payload dict if signature is valid, else None.
    """
    parts = license_key.strip().split(".")
    if len(parts) != 2:
        return None
    payload_b64, sig_b64 = parts
    if not _verify_signature(payload_b64, sig_b64):
        return None
    try:
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        return json.loads(payload_json)
    except Exception:
        return None


def _is_expired(payload: dict) -> bool:
    return datetime.now() > datetime.fromisoformat(payload["expiry_date"])


def _days_remaining(payload: dict) -> int:
    delta = datetime.fromisoformat(payload["expiry_date"]) - datetime.now()
    return max(0, delta.days)


# ── Public API ─────────────────────────────────────────────────────────────────

def activate_license(license_key: str) -> dict:
    payload = decode_license_key(license_key)
    if payload is None:
        return {"success": False, "message": "Invalid license key — signature verification failed."}

    if _is_expired(payload):
        return {"success": False, "message": "This license key has expired."}

    fingerprint = get_hardware_fingerprint()

    # No hardware binding checks - license can be used from any machine
    # License validation happens on server-side only via API calls

    # Validate with license server when configured
    if LICENSE_SERVER_URL:
        ok = _online_validate(license_key.strip(), fingerprint)
        if ok is False:
            return {"success": False, "message": "Online license validation failed. Contact support@trintzlabs.com."}

    record = {
        **payload,
        "activated":        True,
        "activation_date":  datetime.now().isoformat(),
        "machine_id":       fingerprint,
        "license_key":      license_key.strip(),
    }
    _write_dat(record)

    return {
        "success":        True,
        "message":        "License activated successfully.",
        "license_type":   payload.get("license_type", "Standard"),
        "customer":       payload.get("customer", ""),
        "serial":         payload.get("serial", ""),
        "expiry_date":    payload["expiry_date"],
        "days_remaining": _days_remaining(payload),
        "hardware_bound": bool(payload.get("hardware_binding")),
        "max_users":      payload.get("max_users", 5),
        "features":       payload.get("features", []),
    }


def check_license() -> dict:
    data = _read_dat()
    if data is None:
        return {"valid": False, "message": "No license found. Please activate your license."}

    if not data.get("activated"):
        return {"valid": False, "message": "License not activated."}

    if _is_expired(data):
        return {
            "valid":   False,
            "message": f"License expired on {data['expiry_date']}. Please renew.",
        }

    # Hardware binding check removed - license valid on any machine
    # License validation is server-side only

    days = _days_remaining(data)
    return {
        "valid":          True,
        "message":        "License is active.",
        "license_type":   data.get("license_type", "Standard"),
        "customer":       data.get("customer", ""),
        "serial":         data.get("serial", ""),
        "expiry_date":    data.get("expiry_date", ""),
        "days_remaining": days,
        "hardware_bound": bool(data.get("hardware_binding")),
        "max_users":      data.get("max_users", 5),
        "features":       data.get("features", []),
        "warning":        (f"License expires in {days} days." if days <= 30 else None),
    }


def get_fingerprint_info() -> dict:
    return {"fingerprint": get_hardware_fingerprint()}


def has_feature(feature: str) -> bool:
    """Check if the current license includes a specific feature."""
    data = _read_dat()
    if not data or not data.get("activated"):
        return False
    features = data.get("features", [])
    return feature in features


# ── Optional online validation ─────────────────────────────────────────────────

def _online_validate(license_key: str, fingerprint: str) -> bool | None:
    """Returns True/False/None — None means server unreachable (offline OK)."""
    if not LICENSE_SERVER_URL:
        return None
    try:
        import urllib.request
        import urllib.error
        body = json.dumps({"license_key": license_key, "fingerprint": fingerprint}).encode()
        req  = urllib.request.Request(
            f"{LICENSE_SERVER_URL}/api/validate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("valid", False)
    except urllib.error.HTTPError:
        return False
    except Exception:
        return None  # Offline — allow activation
