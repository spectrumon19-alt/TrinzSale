"""
build_dist.py — End-to-end client distribution builder for TrintzPOS.

Run from the project root:
    python build_dist.py

What it does:
  1. Verifies public.pem exists (key pair must be generated first)
  2. Verifies private.pem is NOT present (safety check — must not ship)
  3. Minifies JavaScript files (requires jsmin: pip install jsmin)
  4. Runs PyInstaller to compile the app into dist/TrintzPOS.exe
  5. Creates a client delivery ZIP: dist/TrintzPOS_vX.X.X_YYYY-MM-DD.zip
       containing only: TrintzPOS.exe + INSTALL.txt

Usage:
  pip install pyinstaller jsmin
  python build_dist.py

The resulting ZIP is what you send to the client.
They double-click TrintzPOS.exe, enter their license key, done.
"""

import os
import sys
import shutil
import zipfile
import subprocess
from datetime import date
from pathlib import Path

VERSION = "1.0.0"  # Update per release

BUILD_DIR    = Path("build")
DIST_DIR     = Path("dist")
SPEC_FILE    = Path("trintzpos.spec")
EXE_NAME     = "TrintzPOS.exe"
OUTPUT_ZIP   = DIST_DIR / f"TrintzPOS_v{VERSION}_{date.today().isoformat()}.zip"

NEVER_SHIP = [
    "private.pem",
    "generate_license_key.py",
    "gen_keypair.py",
    "keygen.py",
    "issued_licenses.log",
    "license_serial.txt",
    ".env",
]

INSTALL_TXT = f"""\
TrintzPOS v{VERSION} — Installation Guide
==========================================
Provided by Trintz Data Labs  |  support@trintzlabs.com

REQUIREMENTS
------------
- Windows 10 / 11 (64-bit)
- PostgreSQL 14+ (must be running and accessible)
- Minimum 4 GB RAM, 2 GB free disk space

SETUP
-----
1. Copy TrintzPOS.exe to any folder (e.g. C:\\TrintzPOS\\)
2. In the same folder, create a file named  .env  with your database
   and configuration settings (see .env.example for reference):

     SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
     DB_HOST=localhost
     DB_NAME=pos_db
     DB_USER=your_db_user
     DB_PASSWORD=your_db_password
     DB_PORT=5432
     ALLOWED_ORIGIN=http://localhost:5001

3. Run  TrintzPOS.exe
4. On first launch, paste the license key provided by Trintz Data Labs.
5. The POS will open in your default browser at http://localhost:5001

FIRST-TIME DATABASE SETUP
--------------------------
- Open your browser and go to http://localhost:5001/configureDB.html
  to initialise the database schema automatically, OR
- Run schema.sql against your PostgreSQL database manually.

CREATE FIRST ADMIN USER
-----------------------
After the database is initialised, visit http://localhost:5001/register.html
and create the Super Admin account.

SUPPORT
-------
Email : support@trintzlabs.com
Hours : Mon–Sat, 9 AM – 6 PM IST

© {date.today().year} Trintz Data Labs. All rights reserved.
Unauthorised copying, redistribution, or reverse engineering is prohibited.
"""


def step(msg: str):
    print(f"\n[{'=':=<3}] {msg}")


def abort(msg: str):
    print(f"\n[ERROR] {msg}")
    sys.exit(1)


def check_prerequisites():
    step("Checking prerequisites")

    if not Path("public.pem").exists():
        abort("public.pem not found. Run gen_keypair.py first, then copy public.pem here.")

    for bad in NEVER_SHIP:
        if Path(bad).exists():
            if bad == "private.pem":
                abort(
                    "private.pem is present in the project directory!\n"
                    "       Move it to a secure vault and delete it from here before building.\n"
                    "       NEVER include private.pem in a client distribution."
                )
            # For other internal files, just warn
            print(f"  [WARN] {bad} exists — it will NOT be included in the build.")

    # Check pyinstaller is available
    result = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        abort("PyInstaller not found. Install it: pip install pyinstaller")

    print("  Prerequisites OK")


def minify_js():
    step("Minifying JavaScript")
    try:
        from jsmin import jsmin
    except ImportError:
        print("  [SKIP] jsmin not installed (pip install jsmin) — shipping unminified JS")
        return

    minified = 0
    for js_file in Path(".").glob("*.js"):
        if js_file.name.endswith(".min.js"):
            continue
        try:
            original = js_file.read_text(encoding="utf-8", errors="ignore")
            compressed = jsmin(original)
            js_file.write_text(compressed, encoding="utf-8")
            saved = len(original) - len(compressed)
            print(f"  {js_file.name}: saved {saved:,} bytes")
            minified += 1
        except Exception as e:
            print(f"  [WARN] Could not minify {js_file.name}: {e}")

    print(f"  Minified {minified} file(s)")


def run_pyinstaller():
    step("Running PyInstaller")
    if not SPEC_FILE.exists():
        abort(f"{SPEC_FILE} not found.")

    # Clean previous build artefacts
    for d in (BUILD_DIR, DIST_DIR / EXE_NAME):
        if d.exists():
            shutil.rmtree(d)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"],
        check=False,
    )
    if result.returncode != 0:
        abort("PyInstaller build failed. Check output above.")

    exe_path = DIST_DIR / EXE_NAME
    if not exe_path.exists():
        abort(f"Expected {exe_path} but it was not created.")

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"  Built: {exe_path}  ({size_mb:.1f} MB)")


def create_delivery_zip():
    step(f"Creating client delivery ZIP: {OUTPUT_ZIP}")

    exe_path = DIST_DIR / EXE_NAME
    if not exe_path.exists():
        abort(f"{exe_path} not found — run PyInstaller step first.")

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, EXE_NAME)
        zf.writestr("INSTALL.txt", INSTALL_TXT)

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"  Created: {OUTPUT_ZIP}  ({size_mb:.1f} MB)")
    print(f"  Contents: {EXE_NAME} + INSTALL.txt")


def main():
    print("=" * 60)
    print(f"  TrintzPOS Distribution Builder  v{VERSION}")
    print("=" * 60)

    check_prerequisites()
    minify_js()
    run_pyinstaller()
    create_delivery_zip()

    print()
    print("=" * 60)
    print(f"  BUILD COMPLETE")
    print(f"  Deliver this file to the client:")
    print(f"  {OUTPUT_ZIP.resolve()}")
    print()
    print("  Files NOT included (as required):")
    for f in NEVER_SHIP:
        print(f"    - {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
