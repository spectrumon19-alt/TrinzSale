"""
license_guard.py — Flask middleware that enforces license validity on every API call.

- All /api/* routes require a valid license EXCEPT /api/license/*.
- Static files and HTML pages are always served (so the activation page loads).
- License status is cached for CACHE_TTL seconds to avoid hitting the filesystem
  on every request.
- Returns HTTP 402 Payment Required with a JSON body when the license is invalid.

Set  LICENSE_GUARD_ENABLED=false  in the environment to disable the guard entirely.
This should be done on cloud/SaaS deployments (e.g. Render) where the server is
operated by Trintz and does not need per-client license enforcement.
"""

import os
import time
import threading
from flask import request, jsonify

# Disable entirely when LICENSE_GUARD_ENABLED=false (cloud/SaaS deployments)
_GUARD_ENABLED = os.environ.get("LICENSE_GUARD_ENABLED", "true").lower() not in ("false", "0", "no")

if _GUARD_ENABLED:
    from license_manager import check_license

CACHE_TTL = 300  # seconds — recheck license every 5 minutes

_cache_lock   = threading.Lock()
_cached_at    = 0.0
_cached_result: dict | None = None


def _get_cached_license() -> dict:
    global _cached_at, _cached_result
    now = time.time()
    with _cache_lock:
        if _cached_result is None or (now - _cached_at) > CACHE_TTL:
            _cached_result = check_license()
            _cached_at     = now
        return _cached_result


def invalidate_cache() -> None:
    """Call this after a successful activation so the next request re-reads license.dat."""
    global _cached_at, _cached_result
    with _cache_lock:
        _cached_at    = 0.0
        _cached_result = None


class LicenseGuard:
    """
    Register this on a Flask app to enforce license checks.

    Usage in app.py:
        from license_guard import LicenseGuard
        LicenseGuard(app)

    Disabled automatically when LICENSE_GUARD_ENABLED=false (Render / cloud).
    """

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not _GUARD_ENABLED:
            app.logger.info("LicenseGuard: disabled (LICENSE_GUARD_ENABLED=false)")
            return
        app.logger.info("LicenseGuard: active — all /api/* routes require a valid license")
        app.before_request(self._check)

    @staticmethod
    def _check():
        path = request.path

        # Always allow: license endpoints (activation page needs these)
        if path.startswith("/api/license"):
            return None

        # Always allow: login + register — user must be able to authenticate
        # even before a license is activated (e.g. first-time setup)
        if path in ("/api/login", "/api/register", "/api/logout"):
            return None

        # Always allow: static files, HTML pages, well-known probes
        if not path.startswith("/api/"):
            return None

        result = _get_cached_license()
        if result.get("valid"):
            return None

        return jsonify({
            "error":   "license_required",
            "message": result.get("message", "License invalid."),
            "action":  "Please activate your license at /license_activation.html",
        }), 402
