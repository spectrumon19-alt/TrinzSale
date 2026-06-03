"""
create_customer_dist.py — Build the customer distribution package.

Creates: C:\\Users\\abhis\\OneDrive\\Desktop\\t\\pos\\customer_dist_trintzPos\\

Protection strategy:
  - All Python source (.py) is compiled to bytecode (.pyc) and packed into
    app_code.zip using Python's zipimport protocol.
  - Only a minimal 20-line launcher.py is shipped as readable source
    (contains no business logic — just bootstrap code).
  - Sensitive internal files are hard-excluded.

Run: python create_customer_dist.py
"""

import os
import sys
import shutil
import zipfile
import tempfile
import textwrap
import py_compile
from pathlib import Path
from datetime import date

# ── Paths ──────────────────────────────────────────────────────────────────────

SRC  = Path(__file__).parent.resolve()
DIST = Path(r"C:\Users\abhis\OneDrive\Desktop\t\pos\customer_dist_trintzPos")

PY_VER = f"cp{sys.version_info.major}{sys.version_info.minor}"

# ── Source files to compile into app_code.zip ─────────────────────────────────

ROOT_PY = [
    "app.py", "auth.py", "db.py",
    "license_manager.py", "license_guard.py",
    "limiter.py", "backup_engine.py", "backup_scheduler.py",
    "email_otp.py", "wsgi.py",
]

# ── Files / dirs NEVER shipped to customers ───────────────────────────────────

HARD_EXCLUDE_FILES = {
    "private.pem", "master.key", "license.dat",
    "generate_license_key.py", "gen_keypair.py",
    "build_dist.py", "create_customer_dist.py",
    "predeploy.py", "generate_manual_pdf.py",
    "trintzpos.spec", "keygen.py", "license_server.py",
    "create_superadmin.py", "create_bug_report.py", "serve.py",
    ".env", "issued_licenses.log", "license_serial.txt",
    "trintzpos_manual.pdf",
}

HARD_EXCLUDE_DIRS = {
    "license_admin", "auth_system", ".git", "__pycache__",
    ".venv", "venv", "env", "node_modules", "dist", "build",
    ".idea", ".vscode", "tests", "qa",
}

# HTML pages not shipped (internal dev tools)
SKIP_HTML = {"qry2db.html", "shell.html", "configureDB.html"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def step(msg: str) -> None:
    print(f"\n  [{msg}]")

def ok(msg: str) -> None:
    print(f"    [OK]  {msg}")

def warn(msg: str) -> None:
    print(f"    [!]   {msg}")

def compile_py(src: Path) -> bytes:
    """Compile a .py file and return raw .pyc bytes."""
    tmp = tempfile.mktemp(suffix=".pyc")
    py_compile.compile(str(src), cfile=tmp, optimize=2, doraise=True)
    data = Path(tmp).read_bytes()
    os.unlink(tmp)
    return data


# ── Safety checks ──────────────────────────────────────────────────────────────

def preflight() -> None:
    step("Pre-flight checks")

    if not (SRC / "public.pem").exists():
        sys.exit("  [ERROR] public.pem not found. Run gen_keypair.py first.")

    if (SRC / "private.pem").exists():
        sys.exit(
            "  [ERROR] private.pem is present in the source directory!\n"
            "          Move it to a secure vault before building.\n"
            "          It must NEVER be shipped to customers."
        )

    ok("public.pem present")
    ok("private.pem absent (safe)")


# ── Step 1: Wipe and create fresh dist folder ─────────────────────────────────

def create_dist_dir() -> None:
    step("Creating fresh dist directory")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    ok(str(DIST))


# ── Step 2: Compile Python -> app_code.zip ────────────────────────────────────

def build_app_code_zip() -> None:
    step("Compiling Python source -> app_code.zip")
    zip_path = DIST / "app_code.zip"
    errors = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:

        # Root-level modules
        for fname in ROOT_PY:
            src = SRC / fname
            if not src.exists():
                warn(f"Skipping missing: {fname}")
                continue
            try:
                arc = fname.replace(".py", ".pyc")
                zf.writestr(arc, compile_py(src))
                ok(f"  {fname} -> {arc}")
            except py_compile.PyCompileError as e:
                errors.append(f"{fname}: {e}")

        # routes/ package
        routes_dir = SRC / "routes"
        if routes_dir.exists():
            for py_file in sorted(routes_dir.glob("*.py")):
                try:
                    arc = f"routes/{py_file.name.replace('.py', '.pyc')}"
                    zf.writestr(arc, compile_py(py_file))
                    ok(f"  routes/{py_file.name} -> {arc}")
                except py_compile.PyCompileError as e:
                    errors.append(f"routes/{py_file.name}: {e}")

    if errors:
        print("\n  Compilation errors:")
        for e in errors:
            print(f"    ✗  {e}")
        sys.exit("Build failed due to compilation errors.")

    size_kb = zip_path.stat().st_size // 1024
    ok(f"app_code.zip written ({size_kb} KB)")


# ── Step 3: Write customer launcher ───────────────────────────────────────────

def write_launcher() -> None:
    step("Writing customer launcher")
    launcher = textwrap.dedent(f"""\
        \"\"\"
        TrintzPOS — Customer Launcher
        Compiled build {date.today().isoformat()} · Python {sys.version.split()[0]}
        © 2025 Trintz Data Labs. Proprietary and confidential.
        \"\"\"
        import os, sys, socket
        from dotenv import load_dotenv

        load_dotenv()

        # Resolve app base dir BEFORE importing anything from the zip.
        # Routes use TRINTZ_APP_BASE to resolve runtime paths (tmp_ocr, backups, schema.sql)
        # so they work from inside app_code.zip without needing __file__ to be a real path.
        _base = os.path.dirname(os.path.abspath(__file__))
        os.environ["TRINTZ_APP_BASE"] = _base

        sys.path.insert(0, os.path.join(_base, "app_code.zip"))
        sys.path.insert(1, _base)          # for .env, public.pem, schema.sql

        # Guard: exit immediately if port already occupied
        _port = int(os.environ.get("PORT", 5001))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
            if _s.connect_ex(("127.0.0.1", _port)) == 0:
                print(f"[ERROR] Port {{_port}} is already in use. Stop the existing process first.")
                raise SystemExit(1)

        from app import create_app
        from backup_scheduler import init_scheduler

        _app = create_app()
        init_scheduler(_app)
        _app.run(host="0.0.0.0", port=_port, debug=False)
    """)

    (DIST / "launcher.py").write_text(launcher, encoding="utf-8")
    ok("launcher.py")


# ── Step 4: Write start.bat (Windows) ─────────────────────────────────────────

def write_start_bat() -> None:
    step("Writing Windows startup scripts")
    bat = textwrap.dedent(r"""
        @echo off
        title TrintzPOS
        echo.
        echo   Starting TrintzPOS...
        echo   Open your browser at http://localhost:5001
        echo   Close this window to stop the server.
        echo.
        python launcher.py
        pause
    """).lstrip()
    (DIST / "start.bat").write_text(bat, encoding="utf-8")
    ok("start.bat")

    # Also write a requirements file stripped of internal-only deps
    req_src = SRC / "requirements.txt"
    if req_src.exists():
        lines = req_src.read_text().splitlines()
        # Keep only runtime deps (drop test, build, internal tools)
        skip_prefixes = ("pytest", "playwright", "pyinstaller", "jsmin", "reportlab", "PyMuPDF")
        filtered = [l for l in lines if l.strip() and not l.strip().startswith(skip_prefixes)]
        (DIST / "requirements.txt").write_text("\n".join(filtered) + "\n", encoding="utf-8")
        ok("requirements.txt (trimmed)")


# ── Step 5: Copy static web assets ────────────────────────────────────────────

def copy_static_assets() -> None:
    step("Copying static web assets")

    # HTML pages
    copied_html = 0
    for html in sorted(SRC.glob("*.html")):
        if html.name in SKIP_HTML:
            warn(f"Skipping (dev-only): {html.name}")
            continue
        shutil.copy2(html, DIST / html.name)
        copied_html += 1
    ok(f"{copied_html} HTML pages")

    # CSS
    for css in SRC.glob("*.css"):
        shutil.copy2(css, DIST / css.name)
    ok("CSS files")

    # JS files
    copied_js = 0
    for js in SRC.glob("*.js"):
        shutil.copy2(js, DIST / js.name)
        copied_js += 1
    ok(f"{copied_js} JS files")

    # assets/ directory
    assets_src = SRC / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, DIST / "assets")
        ok("assets/")

    # templates/ directory (email templates etc.)
    tmpl_src = SRC / "templates"
    if tmpl_src.exists():
        shutil.copytree(tmpl_src, DIST / "templates")
        ok("templates/")

    # components/ directory (if exists)
    comp_src = SRC / "components"
    if comp_src.exists():
        shutil.copytree(comp_src, DIST / "components")
        ok("components/")


# ── Step 6: Copy data / config files ──────────────────────────────────────────

def copy_data_files() -> None:
    step("Copying data and config files")

    for fname in ("public.pem", "schema.sql"):
        src = SRC / fname
        if src.exists():
            shutil.copy2(src, DIST / fname)
            ok(fname)
        else:
            warn(f"{fname} not found — skipping")

    # .env.example with customer-friendly defaults
    env_example = textwrap.dedent(f"""\
        # TrintzPOS Configuration — rename this file to  .env  before starting
        # Generated {date.today().isoformat()} · Trintz Data Labs

        # Strong random secret key for JWT tokens
        # Generate: python -c "import secrets; print(secrets.token_hex(32))"
        SECRET_KEY=replace-with-a-strong-random-secret-key

        # PostgreSQL database connection
        DB_HOST=localhost
        DB_NAME=pos_db
        DB_USER=your_db_username
        DB_PASSWORD=your_db_password
        DB_PORT=5432

        # Restrict to your domain in production (e.g. https://pos.yourdomain.com)
        ALLOWED_ORIGIN=*

        # Application port (default 5001)
        PORT=5001

        # Brevo email (optional — for invoice emails)
        # BREVO_API_KEY=your-brevo-api-key
        # BREVO_SENDER_EMAIL=noreply@yourdomain.com
        # BREVO_SENDER_NAME=TrintzPOS
    """)
    (DIST / ".env.example").write_text(env_example, encoding="utf-8")
    ok(".env.example")


# ── Step 7: Write INSTALL.txt ──────────────────────────────────────────────────

def write_install_txt() -> None:
    step("Writing INSTALL.txt")
    txt = textwrap.dedent(f"""\
        TrintzPOS — Installation Guide
        ================================
        Build date : {date.today().isoformat()}
        Provided by: Trintz Data Labs  |  support@trintzlabs.com

        REQUIREMENTS
        ────────────
        • Windows 10 / 11 (64-bit)
        • Python {sys.version.split()[0]} — download from https://python.org
          (Must be the SAME minor version as this build)
        • PostgreSQL 14+ running and accessible
        • 4 GB RAM minimum, 2 GB free disk space
        • Port 5001 open (or change PORT in .env)

        QUICK START (5 steps)
        ─────────────────────
        1. Install Python {sys.version.split()[0]}
           -> Download from https://python.org/downloads
           -> Check "Add Python to PATH" during install

        2. Open a command prompt in this folder and run:
             pip install -r requirements.txt

        3. Configure the database:
           a. Create a PostgreSQL database named  pos_db
           b. Copy .env.example to .env
           c. Edit .env and fill in your DB_HOST, DB_USER, DB_PASSWORD etc.
           d. Generate a secret key:
              python -c "import secrets; print(secrets.token_hex(32))"
              -> Paste the result as SECRET_KEY in .env

        4. Initialise the database schema:
           Open http://localhost:5001/configureDB.html after starting the app

        5. Start TrintzPOS:
           -> Double-click  start.bat
           -> OR run:  python launcher.py
           -> Open browser at:  http://localhost:5001

        FIRST LOGIN
        ───────────
        • Go to http://localhost:5001/register.html
        • Create the Super Admin account
        • Log in with your new credentials

        LICENSE ACTIVATION
        ──────────────────
        On first start you will be prompted for your license key.
        You can also activate at:  http://localhost:5001/license_activation.html
        Contact support@trintzlabs.com to obtain a license key.

        SUPPORT
        ───────
        Email : support@trintzlabs.com
        Hours : Mon–Sat, 9 AM – 6 PM IST

        ─────────────────────────────────────────────────────────
        © 2025 Trintz Data Labs. All rights reserved.
        Unauthorised copying, reverse engineering, or redistribution
        of this software is strictly prohibited.
        ─────────────────────────────────────────────────────────
    """)
    (DIST / "INSTALL.txt").write_text(txt, encoding="utf-8")
    ok("INSTALL.txt")


# ── Step 8: Security audit — verify no sensitive files leaked ─────────────────

def security_audit() -> None:
    step("Security audit")
    leaked = []
    for item in DIST.rglob("*"):
        if item.is_file():
            name = item.name
            if name in HARD_EXCLUDE_FILES:
                leaked.append(str(item.relative_to(DIST)))
            if any(d in item.parts for d in HARD_EXCLUDE_DIRS):
                leaked.append(str(item.relative_to(DIST)))

    if leaked:
        print("\n  [SECURITY ALERT] Sensitive files found in dist — aborting!")
        for f in leaked:
            print(f"    ✗  {f}")
        shutil.rmtree(DIST)
        sys.exit("Distribution aborted. Fix the exclusion list.")

    # Verify no .py source files leaked (except launcher.py)
    py_files = [f for f in DIST.rglob("*.py") if f.name != "launcher.py"]
    if py_files:
        print("\n  [WARN] Uncompiled .py source files found in dist:")
        for f in py_files:
            print(f"    !  {f.relative_to(DIST)}")
    else:
        ok("No raw .py source files in distribution (except launcher.py)")

    ok("No sensitive files detected")


# ── Summary ────────────────────────────────────────────────────────────────────

def summary() -> None:
    total_files = sum(1 for _ in DIST.rglob("*") if _.is_file())
    total_size  = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    size_mb     = total_size / (1024 * 1024)

    print(f"""
  +--------------------------------------------------------------+
  |   CUSTOMER DISTRIBUTION READY                                |
  +--------------------------------------------------------------+
  |  Location : {str(DIST):<48}|
  |  Files    : {total_files:<48}|
  |  Size     : {f'{size_mb:.1f} MB':<48}|
  +--------------------------------------------------------------+
  |  SOURCE CODE PROTECTION                                      |
  |  [OK] All Python compiled to .pyc bytecode                  |
  |  [OK] Bytecode packed into app_code.zip                     |
  |  [OK] private.pem excluded                                  |
  |  [OK] All internal tools excluded                           |
  +--------------------------------------------------------------+
  |  SEND TO CUSTOMER                                            |
  |  Zip the entire folder and share with the client.           |
  |  They run:  pip install -r requirements.txt                 |
  |  Then:      start.bat                                       |
  +--------------------------------------------------------------+
""")


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  TrintzPOS - Customer Distribution Builder")
    print("  " + "=" * 50)

    preflight()
    create_dist_dir()
    build_app_code_zip()
    write_launcher()
    write_start_bat()
    copy_static_assets()
    copy_data_files()
    write_install_txt()
    security_audit()
    summary()
