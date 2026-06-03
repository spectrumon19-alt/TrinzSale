from flask import Flask, session, redirect, url_for, request
from config import Config
from core.db import init_db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure DB is initialised
    init_db(Config.DB_PATH)

    # Register blueprints
    from routes.pages import pages_bp
    from routes.api   import api_bp
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    # Auth gate — every non-login request must have a session
    @app.before_request
    def _require_auth():
        public = {'pages.login', 'pages.logout', 'static'}
        if request.endpoint not in public and not session.get('admin'):
            if request.path.startswith('/api/'):
                from flask import jsonify
                return jsonify({'error': 'Unauthorised'}), 401
            return redirect(url_for('pages.login'))

    # Security headers
    @app.after_request
    def _headers(response):
        response.headers['X-Frame-Options']        = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy']        = 'same-origin'
        response.headers['Cache-Control']          = 'no-store'
        return response

    return app
