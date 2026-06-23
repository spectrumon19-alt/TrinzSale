"""Admin blueprint package. Split from monolithic routes/admin.py into
domain modules. All URL paths are unchanged."""
from .users import admin_users_bp
from .invoices import admin_invoices_bp
from .login_activity import admin_login_bp
from .permissions import admin_perms_bp
from .settings import store_settings_bp
from .token_usage import admin_tokens_bp

ADMIN_BLUEPRINTS = [
    admin_users_bp,
    admin_invoices_bp,
    admin_login_bp,
    admin_perms_bp,
    store_settings_bp,
    admin_tokens_bp,
]
