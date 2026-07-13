"""
License API Blueprint for TrintzERP.
Endpoints: /api/license/status, /api/license/activate, /api/license/fingerprint

When LICENSE_GUARD_ENABLED=false (Render/cloud deployments) these endpoints
return a friendly "not applicable" response instead of failing on missing public.pem.
"""

import os
from flask import Blueprint, jsonify, request
from license_guard import invalidate_cache

license_bp = Blueprint("license", __name__)

_GUARD_ENABLED = os.environ.get("LICENSE_GUARD_ENABLED", "true").lower() not in ("false", "0", "no")


def _not_applicable():
    return jsonify({
        "valid":   True,
        "message": "License management is handled server-side (cloud deployment).",
        "cloud":   True,
    }), 200


@license_bp.route("/license/status", methods=["GET"])
def license_status():
    if not _GUARD_ENABLED:
        return _not_applicable()
    from license_manager import check_license
    result = check_license()
    return jsonify(result), (200 if result.get("valid") else 402)


@license_bp.route("/license/activate", methods=["POST"])
def license_activate():
    if not _GUARD_ENABLED:
        return _not_applicable()
    from license_manager import activate_license
    data = request.get_json(silent=True) or {}
    key  = data.get("license_key", "").strip()
    if not key:
        return jsonify({"success": False, "message": "license_key is required."}), 400
    result = activate_license(key)
    if result.get("success"):
        invalidate_cache()
    return jsonify(result), (200 if result.get("success") else 400)


@license_bp.route("/license/fingerprint", methods=["GET"])
def license_fingerprint():
    if not _GUARD_ENABLED:
        return jsonify({"fingerprint": "N/A (cloud deployment)"}), 200
    from license_manager import get_fingerprint_info
    return jsonify(get_fingerprint_info()), 200
