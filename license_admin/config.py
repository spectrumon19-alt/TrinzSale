import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class Config:
    SECRET_KEY            = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    ADMIN_PASSWORD        = os.environ.get('ADMIN_PASSWORD', 'admin')
    PRIVATE_KEY_PATH      = os.environ.get('PRIVATE_KEY_PATH', str(BASE_DIR / 'keys' / 'private.pem'))
    PUBLIC_KEY_PATH       = os.environ.get('PUBLIC_KEY_PATH', str(BASE_DIR / 'keys' / 'public.pem'))
    DB_PATH               = os.environ.get('DB_PATH', str(BASE_DIR / 'data' / 'licenses.db'))
    PORT                  = int(os.environ.get('PORT', 5002))

    # TrintzPOS source code directory (used as default for distribution builds)
    SOURCE_CODE_DIR       = os.environ.get('SOURCE_CODE_DIR', '')

    # Default base directory where customer distributions are saved
    # Each build creates a sub-folder: DIST_OUTPUT_BASE/CustomerName_YYYY-MM-DD/
    _dist_base            = os.environ.get('DIST_OUTPUT_BASE', str(BASE_DIR / 'distributions'))
    DIST_OUTPUT_BASE      = Path(_dist_base)

    # ── Email — AWS SES (Free: 62,000 emails/month) ────────────────────────────────

    AWS_REGION            = os.environ.get('AWS_REGION',             'us-east-1')
    AWS_ACCESS_KEY_ID     = os.environ.get('AWS_ACCESS_KEY_ID',      '')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY',  '')
    AWS_SES_FROM_EMAIL    = os.environ.get('AWS_SES_FROM_EMAIL',     '')
    AWS_SES_FROM_NAME     = os.environ.get('AWS_SES_FROM_NAME',      'TrintzPOS Support')

    # If explicit SMTP vars not set, derive from Brevo credentials
    SMTP_HOST     = os.environ.get('SMTP_HOST',     'smtp-relay.brevo.com' if os.environ.get('BREVO_API_KEY') else '')
    SMTP_PORT     = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER     = os.environ.get('SMTP_USER',     os.environ.get('BREVO_SMTP_USER',   ''))
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', os.environ.get('BREVO_API_KEY',     ''))
    SMTP_USE_TLS  = os.environ.get('SMTP_USE_TLS',  'true').lower() != 'false'
    SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', os.environ.get('BREVO_SENDER_EMAIL', ''))
    SMTP_FROM_NAME  = os.environ.get('SMTP_FROM_NAME',  os.environ.get('BREVO_SENDER_NAME',  'Trintz Data Labs'))

    SESSION_PERMANENT          = True
    SESSION_COOKIE_HTTPONLY    = True
    SESSION_COOKIE_SAMESITE    = 'Strict'
    PERMANENT_SESSION_LIFETIME = 3600 * 8
