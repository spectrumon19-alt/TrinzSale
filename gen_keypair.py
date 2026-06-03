"""
gen_keypair.py — Run ONCE at Trintz to generate the RSA-2048 signing keypair.

  python gen_keypair.py

Outputs:
  private.pem  — Keep secret. NEVER ship to clients. Used only by generate_license_key.py.
  public.pem   — Ship with every client deployment. Used by the app to verify licenses.

After running:
  1. Copy public.pem into the app distribution.
  2. Store private.pem securely (password manager / secrets vault).
  3. Delete private.pem from any client machine.
"""

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def main():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    priv_path = Path("private.pem")
    pub_path  = Path("public.pem")

    if priv_path.exists() or pub_path.exists():
        answer = input("Key files already exist. Overwrite? (yes/no): ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return

    priv_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    pub_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    print(f"[OK] private.pem written — KEEP SECRET, never ship to clients")
    print(f"[OK] public.pem written  — ship with every client deployment")


if __name__ == "__main__":
    main()
