"""
dist_builder.py — Standalone customer distribution builder.

Compiles TrintzPOS source -> bytecode zip + static assets.
Completely isolated: no dependency on the main TrintzPOS app.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import textwrap
import smtplib
import py_compile
from pathlib import Path
from datetime import date
from email import encoders as email_encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ── Files / dirs NEVER shipped ────────────────────────────────────────────────

_EXCLUDE_FILES = {
    "private.pem", "master.key", "license.dat",
    "generate_license_key.py", "gen_keypair.py",
    "build_dist.py", "create_customer_dist.py",
    "predeploy.py", "generate_manual_pdf.py",
    "trintzpos.spec", "keygen.py", "license_server.py",
    "create_superadmin.py", "create_bug_report.py", "serve.py",
    ".env", "issued_licenses.log", "license_serial.txt",
    "trintzpos_manual.pdf",
}

_EXCLUDE_DIRS = {
    "license_admin", "auth_system", ".git", "__pycache__",
    ".venv", "venv", "env", "node_modules", "dist", "build",
    ".idea", ".vscode", "tests", "qa",
}

_SKIP_HTML = {"qry2db.html", "shell.html", "configureDB.html"}

_ROOT_PY = [
    "app.py", "auth.py", "db.py",
    "license_manager.py", "license_guard.py",
    "limiter.py", "backup_engine.py", "backup_scheduler.py",
    "email_otp.py", "wsgi.py",
]

_SKIP_RUNTIME_DEPS = (
    "pytest", "playwright", "pyinstaller", "jsmin",
    "reportlab", "PyMuPDF",
)


class BuildError(Exception):
    pass


class DistBuilder:
    """
    Build a customer-shippable distribution from TrintzPOS source.

    Usage:
        b = DistBuilder(source_dir='/path/to/source', output_dir='/path/to/out')
        result = b.build()
        if result['success']:
            zip_path = b.make_zip()
            b.send_email(to='customer@example.com', zip_path=zip_path, smtp_cfg={...})
    """

    def __init__(self, source_dir: str, output_dir: str, customer_name: str = 'Customer'):
        self.src  = Path(source_dir).resolve()
        self.out  = Path(output_dir).resolve()
        self.customer_name = customer_name
        self.log: list[dict] = []   # list of {level, msg}

    # ── Logging ────────────────────────────────────────────────────────────────

    def _ok(self, msg: str) -> None:
        self.log.append({'level': 'ok',   'msg': msg})

    def _info(self, msg: str) -> None:
        self.log.append({'level': 'info', 'msg': msg})

    def _warn(self, msg: str) -> None:
        self.log.append({'level': 'warn', 'msg': msg})

    # ── Pre-flight ─────────────────────────────────────────────────────────────

    def _preflight(self) -> None:
        self._info("Running pre-flight checks...")

        if not self.src.exists():
            raise BuildError(f"Source directory not found: {self.src}")

        if not (self.src / "app.py").exists():
            raise BuildError(f"app.py not found in source directory. Is this the right folder?")

        if not (self.src / "public.pem").exists():
            raise BuildError("public.pem not found in source directory.")

        if (self.src / "private.pem").exists():
            raise BuildError(
                "private.pem is present in the source directory. "
                "Move it to a secure vault before building."
            )

        self._ok("Source directory validated")
        self._ok("public.pem present, private.pem absent")

    # ── Create output dir ──────────────────────────────────────────────────────

    def _create_output_dir(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self._ok(f"Output directory created: {self.out}")

    # ── Compile Python -> app_code.zip ────────────────────────────────────────

    @staticmethod
    def _compile_file(src_path: Path) -> bytes:
        tmp = tempfile.mktemp(suffix=".pyc")
        py_compile.compile(str(src_path), cfile=tmp, optimize=2, doraise=True)
        data = Path(tmp).read_bytes()
        os.unlink(tmp)
        return data

    def _build_app_code_zip(self) -> None:
        self._info("Compiling Python source to bytecode...")
        zip_path = self.out / "app_code.zip"
        errors   = []
        compiled = 0

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:

            for fname in _ROOT_PY:
                src = self.src / fname
                if not src.exists():
                    self._warn(f"Skipping missing: {fname}")
                    continue
                try:
                    zf.writestr(fname.replace(".py", ".pyc"), self._compile_file(src))
                    compiled += 1
                except py_compile.PyCompileError as e:
                    errors.append(str(e))

            routes_dir = self.src / "routes"
            if routes_dir.exists():
                for py in sorted(routes_dir.glob("*.py")):
                    try:
                        arc = f"routes/{py.name.replace('.py', '.pyc')}"
                        zf.writestr(arc, self._compile_file(py))
                        compiled += 1
                    except py_compile.PyCompileError as e:
                        errors.append(str(e))

        if errors:
            for e in errors:
                self._warn(f"Compile error: {e}")
            raise BuildError(f"{len(errors)} file(s) failed to compile.")

        size_kb = zip_path.stat().st_size // 1024
        self._ok(f"app_code.zip: {compiled} modules compiled ({size_kb} KB)")

    # ── Launcher ───────────────────────────────────────────────────────────────

    def _write_launcher(self) -> None:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        launcher = textwrap.dedent(f"""\
            \"\"\"
            TrintzPOS Customer Launcher
            Build {date.today().isoformat()} | Python {py_ver}
            (c) 2025 Trintz Data Labs. Proprietary and confidential.
            \"\"\"
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
                    print(f"[ERROR] Port {{_port}} is already in use.")
                    raise SystemExit(1)

            from app import create_app
            from backup_scheduler import init_scheduler

            _app = create_app()
            init_scheduler(_app)
            _app.run(host="0.0.0.0", port=_port, debug=False)
        """)
        (self.out / "launcher.py").write_text(launcher, encoding="utf-8")
        self._ok("launcher.py written")

    # ── Start scripts ──────────────────────────────────────────────────────────

    def _write_start_scripts(self) -> None:
        bat = "@echo off\r\ntitle TrintzPOS\r\necho.\r\necho   TrintzPOS starting... open http://localhost:5001\r\necho   Close this window to stop the server.\r\necho.\r\npython launcher.py\r\npause\r\n"
        (self.out / "start.bat").write_text(bat, encoding="utf-8")
        self._ok("start.bat written")

        req_src = self.src / "requirements.txt"
        if req_src.exists():
            lines    = req_src.read_text().splitlines()
            filtered = [l for l in lines if l.strip() and not l.strip().lower().startswith(_SKIP_RUNTIME_DEPS)]
            (self.out / "requirements.txt").write_text("\n".join(filtered) + "\n", encoding="utf-8")
            self._ok("requirements.txt written (build-only deps stripped)")

    # ── Static assets ──────────────────────────────────────────────────────────

    def _copy_static_assets(self) -> None:
        self._info("Copying static assets...")
        skipped = 0

        for html in sorted(self.src.glob("*.html")):
            if html.name in _SKIP_HTML:
                skipped += 1
                continue
            shutil.copy2(html, self.out / html.name)

        for css in self.src.glob("*.css"):
            shutil.copy2(css, self.out / css.name)

        for js in self.src.glob("*.js"):
            shutil.copy2(js, self.out / js.name)

        for subdir in ("assets", "templates", "components"):
            src = self.src / subdir
            if src.exists():
                shutil.copytree(src, self.out / subdir)

        self._ok(f"Static assets copied ({skipped} dev-only pages excluded)")

    # ── Data files ─────────────────────────────────────────────────────────────

    def _copy_data_files(self) -> None:
        self._info("Copying data files...")
        for fname in ("public.pem", "schema.sql"):
            src = self.src / fname
            if src.exists():
                shutil.copy2(src, self.out / fname)
                self._ok(f"{fname} copied")
            else:
                self._warn(f"{fname} not found in source")

        env_example = textwrap.dedent(f"""\
            # TrintzPOS Configuration — rename this file to .env before starting
            # Generated {date.today().isoformat()} for {self.customer_name}

            # Generate a strong random key:
            # python -c "import secrets; print(secrets.token_hex(32))"
            SECRET_KEY=replace-with-a-strong-random-secret-key

            DB_HOST=localhost
            DB_NAME=pos_db
            DB_USER=your_db_username
            DB_PASSWORD=your_db_password
            DB_PORT=5432

            ALLOWED_ORIGIN=*
            PORT=5001

            # Brevo email (optional)
            # BREVO_API_KEY=your-brevo-api-key
            # BREVO_SENDER_EMAIL=noreply@yourdomain.com
            # BREVO_SENDER_NAME=TrintzPOS
        """)
        (self.out / ".env.example").write_text(env_example, encoding="utf-8")
        self._ok(".env.example written")

    # ── INSTALL.txt ────────────────────────────────────────────────────────────

    def _write_install_txt(self) -> None:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        txt = textwrap.dedent(f"""\
            TrintzPOS - Installation Guide
            ================================
            Prepared for : {self.customer_name}
            Build date   : {date.today().isoformat()}
            Python version: {py_ver}
            Support      : support@trintzlabs.com

            REQUIREMENTS
            ------------
            - Windows 10/11 (64-bit)
            - Python {py_ver} (same version as this build)
              Download: https://python.org/downloads
            - PostgreSQL 14+
            - Port 5001 available

            SETUP (5 steps)
            ---------------
            1. Install Python {py_ver}
               Check "Add Python to PATH" during install.

            2. Open Command Prompt in this folder, run:
                 pip install -r requirements.txt

            3. Configure database:
               a. Create a PostgreSQL database named pos_db
               b. Copy .env.example to .env
               c. Fill in DB_HOST, DB_USER, DB_PASSWORD in .env
               d. Generate secret key:
                  python -c "import secrets; print(secrets.token_hex(32))"
                  Paste as SECRET_KEY in .env

            4. Start the app:
               Double-click start.bat  (or run: python launcher.py)
               Open browser: http://localhost:5001

            5. Initialise database:
               Go to http://localhost:5001/register.html
               Create your Super Admin account.

            LICENSE ACTIVATION
            ------------------
            On first start you will be prompted for your license key.
            To activate: http://localhost:5001/license_activation.html

            SUPPORT
            -------
            Email : support@trintzlabs.com
            Hours : Mon-Sat, 9 AM - 6 PM IST

            (c) 2025 Trintz Data Labs. All rights reserved.
        """)
        (self.out / "INSTALL.txt").write_text(txt, encoding="utf-8")
        self._ok("INSTALL.txt written")

    # ── Security audit ─────────────────────────────────────────────────────────

    def _security_audit(self) -> None:
        self._info("Running security audit...")
        leaked = []
        for item in self.out.rglob("*"):
            if item.is_file() and item.name in _EXCLUDE_FILES:
                leaked.append(str(item.relative_to(self.out)))

        if leaked:
            shutil.rmtree(self.out)
            raise BuildError(f"Security leak detected: {', '.join(leaked)}")

        py_files = [f for f in self.out.rglob("*.py") if f.name != "launcher.py"]
        if py_files:
            self._warn(f"{len(py_files)} uncompiled .py file(s) found (non-critical): "
                       + ", ".join(f.name for f in py_files[:3]))
        else:
            self._ok("No raw .py source in distribution")

        self._ok("Security audit passed")

    # ── Stats ──────────────────────────────────────────────────────────────────

    def _stats(self) -> dict:
        files    = sum(1 for _ in self.out.rglob("*") if _.is_file())
        size_mb  = sum(f.stat().st_size for f in self.out.rglob("*") if f.is_file()) / 1_048_576
        return {'files': files, 'size_mb': round(size_mb, 1)}

    # ── Public: build ──────────────────────────────────────────────────────────

    def build(self) -> dict:
        """
        Run the full distribution build.
        Returns {'success': bool, 'output_dir': str, 'stats': {...}, 'log': [...], 'error': str}
        """
        try:
            self._preflight()
            self._create_output_dir()
            self._build_app_code_zip()
            self._write_launcher()
            self._write_start_scripts()
            self._copy_static_assets()
            self._copy_data_files()
            self._write_install_txt()
            self._security_audit()
            stats = self._stats()
            self._ok(f"Build complete: {stats['files']} files, {stats['size_mb']} MB")
            return {
                'success': True,
                'output_dir': str(self.out),
                'stats': stats,
                'log': self.log,
            }
        except (BuildError, Exception) as e:
            self._warn(f"Build failed: {e}")
            return {'success': False, 'error': str(e), 'log': self.log}

    # ── Public: zip output ─────────────────────────────────────────────────────

    def make_zip(self) -> str:
        """
        Create a ZIP archive of the output directory.
        Returns the path to the ZIP file (placed beside output dir).
        """
        zip_base = str(self.out) + "_package"
        shutil.make_archive(zip_base, "zip", self.out)
        zip_path = zip_base + ".zip"
        size_mb  = Path(zip_path).stat().st_size / 1_048_576
        self._ok(f"ZIP created: {zip_path} ({size_mb:.1f} MB)")
        return zip_path

    # ── Public: send email ─────────────────────────────────────────────────────

    def send_email(self, to_email: str, zip_path: str, smtp_cfg: dict = None,
                   serial: str = '', subject_prefix: str = 'TrintzPOS') -> dict:
        """
        Send the distribution ZIP by email via Brevo SMTP (not REST API).
        SMTP is more reliable for attachments than the REST API.

        Returns {'success': bool, 'error': str}
        """
        from config import Config

        zip_file = Path(zip_path)
        if not zip_file.exists():
            return {'success': False, 'error': 'ZIP file not found.'}

        size_mb = zip_file.stat().st_size / 1_048_576
        if size_mb > 10:
            return {
                'success': False,
                'error': f'ZIP is {size_mb:.1f} MB — exceeds the 10 MB email attachment limit. '
                         'The package was saved to the output folder; share it via file transfer instead.'
            }

        subject = "Your TrintzPOS Installation Package"
        if serial:
            subject += f" — {serial}"

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        plain = textwrap.dedent(f"""\
            Dear {self.customer_name},

            Your TrintzPOS installation package is attached to this email.

            QUICK START
            -----------
            1. Extract the ZIP to a folder (e.g. C:\\TrintzPOS\\)
            2. Open Command Prompt in that folder and run:
                 pip install -r requirements.txt
            3. Copy .env.example to .env and fill in your database details
            4. Double-click start.bat to launch the server
            5. Open your browser at: http://localhost:5001
            6. Activate your license when prompted

            Python {py_ver} must be installed (same version as this build).
            Download from: https://python.org/downloads
            (Check "Add Python to PATH" during install)

            Full instructions are inside INSTALL.txt in the ZIP.

            For support: support@trintzlabs.com

            Best regards,
            Trintz Data Labs
        """)

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,#4f46e5,#2563eb);padding:32px 36px;text-align:center;">
        <div style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-0.5px;">TrintzPOS</div>
        <div style="font-size:13px;color:#c7d2fe;margin-top:4px;">Your installation package is ready</div>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:32px 36px;">
        <p style="margin:0 0 16px;font-size:15px;color:#374151;">Dear <strong>{self.customer_name}</strong>,</p>
        <p style="margin:0 0 24px;font-size:14px;color:#6b7280;line-height:1.6;">
          Your TrintzPOS installation package is attached to this email as a ZIP file.
          Follow the steps below to get started.
        </p>

        <!-- Steps -->
        <div style="background:#f8fafc;border-radius:12px;padding:20px 24px;margin-bottom:24px;">
          <div style="font-size:13px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:14px;">
            Quick Setup Guide
          </div>
          {''.join(f'<div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:10px;"><div style="width:22px;height:22px;background:#4f46e5;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;">{i}</div><div style="font-size:13px;color:#4b5563;line-height:1.5;">{s}</div></div>' for i, s in [
            (1, 'Extract the ZIP to a folder on your computer (e.g. <code style="background:#e5e7eb;padding:1px 5px;border-radius:4px;">C:\\TrintzPOS\\</code>)'),
            (2, f'Install Python {py_ver} from <strong>python.org/downloads</strong> — check <strong>"Add Python to PATH"</strong>'),
            (3, 'Open Command Prompt in the extracted folder and run: <code style="background:#e5e7eb;padding:1px 5px;border-radius:4px;">pip install -r requirements.txt</code>'),
            (4, 'Copy <code style="background:#e5e7eb;padding:1px 5px;border-radius:4px;">.env.example</code> to <code style="background:#e5e7eb;padding:1px 5px;border-radius:4px;">.env</code> and fill in your database details'),
            (5, 'Double-click <code style="background:#e5e7eb;padding:1px 5px;border-radius:4px;">start.bat</code> to launch. Open browser at <strong>http://localhost:5001</strong>'),
          ])}
        </div>

        {'<div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:12px 16px;margin-bottom:24px;font-size:13px;color:#92400e;"><strong>License key required:</strong> You will be prompted to enter your license key on first launch. Contact support if you need your key.</div>' if serial else ''}

        <p style="font-size:13px;color:#6b7280;">
          Full setup instructions are inside <strong>INSTALL.txt</strong> in the ZIP archive.
        </p>
      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:20px 36px;text-align:center;">
        <p style="margin:0;font-size:12px;color:#9ca3af;">
          Questions? Email us at
          <a href="mailto:support@trintzlabs.com" style="color:#4f46e5;text-decoration:none;">support@trintzlabs.com</a>
        </p>
        <p style="margin:8px 0 0;font-size:11px;color:#d1d5db;">
          &copy; 2025 Trintz Data Labs &middot; All rights reserved
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

        # Send via AWS SES with attachment
        try:
            import boto3
            from botocore.exceptions import ClientError

            access_key = Config.AWS_ACCESS_KEY_ID
            secret_key = Config.AWS_SECRET_ACCESS_KEY
            region = Config.AWS_REGION
            from_email = Config.AWS_SES_FROM_EMAIL
            from_name = Config.AWS_SES_FROM_NAME

            if not access_key or not secret_key or not from_email:
                return {'success': False, 'error': 'AWS credentials or AWS_SES_FROM_EMAIL not configured in .env'}

            # Initialize SES client
            ses_client = boto3.client(
                'ses',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )

            # Build email with MIME message (for attachment support)
            msg = MIMEMultipart('mixed')
            msg['Subject'] = subject
            msg['From'] = f'{from_name} <{from_email}>'
            msg['To'] = to_email
            msg.attach(MIMEText(html, 'html', 'utf-8'))

            # Attach ZIP file
            with open(zip_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                email_encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment', filename=zip_file.name)
                msg.attach(part)

            # Send via SES
            response = ses_client.send_raw_email(
                Source=from_email,
                Destinations=[to_email],
                RawMessage={'Data': msg.as_string()},
            )

            message_id = response.get('MessageId', '')
            self._ok(f"Email sent to {to_email} via AWS SES (ID: {message_id})")
            return {'success': True, 'message': f'Sent to {to_email}', 'message_id': message_id}

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            err = f'AWS SES error ({error_code}): {error_msg}'
            self._warn(f"Email failed: {err}")
            return {'success': False, 'error': err}
        except ImportError:
            err = 'boto3 not installed. Run: pip install boto3'
            self._warn(f"Email failed: {err}")
            return {'success': False, 'error': err}
        except Exception as e:
            err = str(e)
            self._warn(f"Email failed: {err}")
            return {'success': False, 'error': err}
