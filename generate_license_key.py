"""
generate_license_key.py — Internal Trintz Data Labs tool to issue signed license keys.

NEVER ship this file or private.pem to clients.

Usage:
  python generate_license_key.py

Prompts for:
  - Customer name
  - Customer email
  - License type (Standard / Professional / Enterprise)
  - Expiry date (YYYY-MM-DD)
  - Hardware binding (yes/no)
  - Machine ID (optional — leave blank to bind on first activation)
  - Max users
  - Feature flags (comma-separated: pos,crm,reports,knowledge,gst,tally)

Outputs a license key string the client pastes into license_activation.html.

Requires private.pem in the same directory.
"""

import base64
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


SERIAL_FILE = Path("license_serial.txt")

ALL_FEATURES = ["pos", "crm", "reports", "knowledge", "gst", "tally"]


def _load_private_key():
    pem_path = Path("private.pem")
    if not pem_path.exists():
        sys.exit("[ERROR] private.pem not found. Run gen_keypair.py first.")
    with open(pem_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _next_serial() -> str:
    year = date.today().year
    n = 1
    if SERIAL_FILE.exists():
        try:
            n = int(SERIAL_FILE.read_text().strip()) + 1
        except ValueError:
            n = 1
    SERIAL_FILE.write_text(str(n))
    return f"TDL-{year}-{n:04d}"


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val if val else default


def _sign(private_key, payload_b64: str) -> str:
    sig = private_key.sign(
        payload_b64.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.urlsafe_b64encode(sig).decode()


def main():
    print("=" * 60)
    print("  TrintzERP License Key Generator  —  Trintz Data Labs")
    print("=" * 60)
    print()

    private_key = _load_private_key()

    customer     = _prompt("Customer name")
    email        = _prompt("Customer email")
    license_type = _prompt("License type (Standard/Professional/Enterprise)", "Professional")
    expiry_str   = _prompt("Expiry date (YYYY-MM-DD)", "")

    # Validate expiry
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        if expiry_date <= date.today():
            sys.exit("[ERROR] Expiry date must be in the future.")
    except ValueError:
        sys.exit("[ERROR] Invalid date format. Use YYYY-MM-DD.")

    hardware_binding_str = _prompt("Hardware binding? (yes/no)", "yes")
    hardware_binding     = hardware_binding_str.lower() in ("yes", "y")

    machine_id_input = ""
    if hardware_binding:
        machine_id_input = _prompt("Machine fingerprint (leave blank to bind on first activation)", "")

    max_users_str = _prompt("Max users", "5")
    try:
        max_users = int(max_users_str)
    except ValueError:
        max_users = 5

    features_str = _prompt(
        f"Features ({', '.join(ALL_FEATURES)})",
        ",".join(ALL_FEATURES)
    )
    features = [f.strip() for f in features_str.split(",") if f.strip()]

    serial = _next_serial()

    payload = {
        "customer":         customer,
        "email":            email,
        "license_type":     license_type,
        "expiry_date":      expiry_str,
        "hardware_binding": hardware_binding,
        "machine_id":       machine_id_input if machine_id_input else None,
        "max_users":        max_users,
        "features":         features,
        "issued_at":        date.today().isoformat(),
        "serial":           serial,
    }

    payload_json  = json.dumps(payload, separators=(",", ":"))
    payload_b64   = base64.urlsafe_b64encode(payload_json.encode()).decode()
    signature_b64 = _sign(private_key, payload_b64)

    license_key = f"{payload_b64}.{signature_b64}"

    print()
    print("=" * 60)
    print(f"  Serial : {serial}")
    print(f"  Customer: {customer}")
    print(f"  Expires : {expiry_str}  ({(expiry_date - date.today()).days} days)")
    print(f"  Type    : {license_type}  |  Max users: {max_users}")
    print(f"  HW-bound: {hardware_binding}")
    print()
    print("  LICENSE KEY (give this to the client):")
    print()
    print(license_key)
    print()
    print("=" * 60)

    # Save to a log file (internal records)
    log_file = Path("issued_licenses.log")
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(json.dumps({
            **payload,
            "key_prefix": license_key[:32] + "...",
        }) + "\n")
    print(f"  Logged to {log_file}")


if __name__ == "__main__":
    main()
