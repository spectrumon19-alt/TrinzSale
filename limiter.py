"""
Shared Flask-Limiter instance.

Initialized here (not in app.py) to avoid circular imports when
route modules import the limiter directly.

Usage in routes:
    from limiter import limiter

    @limiter.limit("10 per minute")
    def my_route():
        ...

Initialized against the app via limiter.init_app(app) in app.py.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # no global limit — only explicit per-route limits
    storage_uri="memory://",    # in-process store; use Redis URI for multi-worker
)
