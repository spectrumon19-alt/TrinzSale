import os
import sys
from flask import Flask, send_from_directory, request
from flask_cors import CORS
from dotenv import load_dotenv
from gzip import GzipFile
import io

# Load environment variables
load_dotenv()

# Resolve the base directory that holds HTML/CSS/JS static files.
# Priority:
#   1. TRINTZ_BASE_DIR  — set by PyInstaller launcher (sys._MEIPASS path)
#   2. TRINTZ_APP_BASE  — set by zip-based launcher.py before any imports
#   3. sys._MEIPASS     — PyInstaller frozen bundle fallback
#   4. __file__ dir     — normal dev mode (app.py is a real file on disk)
def _resolve_base_dir() -> str:
    if os.environ.get("TRINTZ_BASE_DIR"):
        return os.environ["TRINTZ_BASE_DIR"]
    if os.environ.get("TRINTZ_APP_BASE"):
        return os.environ["TRINTZ_APP_BASE"]
    if getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    # __file__ may point inside a .zip — use only if it's a real path
    f = os.path.abspath(__file__)
    if ".zip" not in f.replace("\\", "/"):
        return os.path.dirname(f)
    # Last resort: working directory
    return os.getcwd()

_BASE_DIR = _resolve_base_dir()


def create_app():
    app = Flask(__name__, static_folder=_BASE_DIR)
    # CORS — restrict to configured origin in production; '*' only as fallback for dev
    _allowed_origin = os.environ.get('ALLOWED_ORIGIN', '*')
    CORS(app, methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
         allow_headers=['Content-Type', 'Authorization'],
         origins=_allowed_origin,
         supports_credentials=(_allowed_origin != '*'))
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    if not app.config['SECRET_KEY']:
        raise RuntimeError("SECRET_KEY environment variable is not set.")

    # License enforcement — blocks all /api/* routes when license is invalid
    from license_guard import LicenseGuard
    LicenseGuard(app)

    # Rate limiting (BUG-009 fix)
    from limiter import limiter
    limiter.init_app(app)
    
    # Gzip compression for JSON API responses (big win for slow connections)
    @app.after_request
    def gzip_response(response):
        # Only compress JSON API responses (not file streams from send_from_directory)
        content_type = response.content_type or ''
        if 'application/json' in content_type and response.status_code < 400:
            # Skip if already compressed
            if response.headers.get('Content-Encoding'):
                return response
            # Skip if response is a file stream (direct passthrough)
            if response.direct_passthrough:
                return response
            data = response.get_data()
            if len(data) < 500:
                return response
            
            gzip_buffer = io.BytesIO()
            with GzipFile(fileobj=gzip_buffer, mode='wb') as f:
                f.write(data)
            gzip_buffer.seek(0)
            response.set_data(gzip_buffer.read())
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Vary'] = 'Accept-Encoding'
        return response
    
    # Security headers + cache policy
    @app.after_request
    def security_headers(response):
        ct = response.content_type or ''

        # ── Prevent caching of sensitive pages and API responses ──────────────
        if 'text/html' in ct or 'application/json' in ct:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
            response.headers['Pragma']         = 'no-cache'
            response.headers['Expires']        = '0'

        # ── Cache static assets (CSS / JS / images / fonts) ──────────────────
        elif any(x in ct for x in ('text/css', 'application/javascript', 'text/javascript',
                                    'image/', 'font/', 'application/font', 'text/plain')):
            response.headers['Cache-Control'] = 'public, max-age=86400'

        # ── Security headers on every response ────────────────────────────────
        response.headers['X-Content-Type-Options']  = 'nosniff'
        response.headers['X-Frame-Options']          = 'SAMEORIGIN'
        response.headers['X-XSS-Protection']         = '1; mode=block'
        response.headers['Referrer-Policy']          = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']       = 'camera=(self), microphone=(), geolocation=()'

        # Content Security Policy — blocks XSS, injected scripts, clickjacking
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' "
                "https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )

        # HSTS — force HTTPS for 1 year (only effective when served over HTTPS)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        # Remove server fingerprinting header
        response.headers.pop('Server', None)

        return response
    
    # Register blueprints
    from routes.auth import auth_bp
    from routes.products import products_bp
    from routes.sales import sales_bp
    from routes.inventory import inventory_bp
    from routes.reports import reports_bp
    from routes.admin import admin_bp
    from routes.purchase import purchase_bp
    from routes.suppliers import suppliers_bp
    from routes.supplier_data import supplier_data_bp
    from routes.data_upload import data_upload_bp
    from routes.service import service_bp
    from routes.credit import credit_bp
    from routes.totp import totp_bp
    from routes.returns import returns_bp
    from routes.dashboard import dashboard_bp
    from routes.gst_reports import gst_reports_bp
    from routes.crm import crm_bp
    from routes.ocr_excel import ocr_excel_bp
    from routes.tally_export import tally_export_bp
    from routes.backup import backup_bp
    from routes.email_invoice import email_invoice_bp
    from routes.chat import chat_bp
    from routes.ai_settings import ai_settings_bp
    from routes.knowledge import knowledge_bp
    from routes.license import license_bp
    from routes.data_export import data_export_bp

    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(products_bp, url_prefix='/api')
    app.register_blueprint(sales_bp, url_prefix='/api')
    app.register_blueprint(inventory_bp, url_prefix='/api')
    app.register_blueprint(reports_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/api')
    app.register_blueprint(purchase_bp, url_prefix='/api')
    app.register_blueprint(suppliers_bp, url_prefix='/api')
    app.register_blueprint(supplier_data_bp, url_prefix='/api')
    app.register_blueprint(data_upload_bp, url_prefix='/api')
    app.register_blueprint(service_bp, url_prefix='/api')
    app.register_blueprint(credit_bp, url_prefix='/api')
    app.register_blueprint(totp_bp,    url_prefix='/api')
    app.register_blueprint(returns_bp, url_prefix='/api')
    app.register_blueprint(dashboard_bp, url_prefix='/api')
    app.register_blueprint(gst_reports_bp, url_prefix='/api')
    app.register_blueprint(crm_bp, url_prefix='/api')
    app.register_blueprint(ocr_excel_bp, url_prefix='/api')
    app.register_blueprint(tally_export_bp, url_prefix='/api')
    app.register_blueprint(backup_bp, url_prefix='/api')
    app.register_blueprint(email_invoice_bp, url_prefix='/api')
    app.register_blueprint(chat_bp, url_prefix='/api')
    app.register_blueprint(ai_settings_bp, url_prefix='/api')
    app.register_blueprint(knowledge_bp, url_prefix='/api')
    app.register_blueprint(license_bp, url_prefix='/api')
    app.register_blueprint(data_export_bp, url_prefix='/api')

    # Silence Chrome DevTools probe (avoids noisy 404 in dev logs)
    @app.route('/.well-known/appspecific/com.chrome.devtools.json')
    def chrome_devtools_probe():
        from flask import jsonify
        return jsonify({}), 200

    # Serve static files
    @app.route('/')
    def index():
        return send_from_directory(_BASE_DIR, 'index.html')

    @app.route('/<path:filename>')
    def static_files(filename):
        return send_from_directory(_BASE_DIR, filename)

    # Serve template files
    @app.route('/templates/<path:filename>')
    def template_files(filename):
        return send_from_directory(os.path.join(_BASE_DIR, 'templates'), filename)

    # Serve schema.sql file
    @app.route('/schema.sql')
    def schema_sql():
        return send_from_directory(_BASE_DIR, 'schema.sql')
    
    # Teardown: release connection pool on app shutdown
    @app.teardown_appcontext
    def close_db_pool(exception=None):
        pass  # Pool is shared across requests, closed at process exit
    
    return app

if __name__ == '__main__':
    import os
    import socket
    port = int(os.environ.get("PORT", 5001))
    # Guard: exit immediately if port is already occupied
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        if _s.connect_ex(('127.0.0.1', port)) == 0:
            print(f"\n[ERROR] Port {port} is already in use — server may already be running.")
            print("  Stop the existing process first, then restart.\n")
            raise SystemExit(1)
    app = create_app()
    from backup_scheduler import init_scheduler
    init_scheduler(app)
    app.run(debug=False, host='0.0.0.0', port=port)