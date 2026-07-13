"""Brevo HTTP API email sender — used by Flask registration + login flow.

Switched from SMTP to the Brevo transactional email REST API so the app
works on Render (free tier blocks outbound SMTP on port 587).
API docs: https://developers.brevo.com/reference/sendtransacemail
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# ── Registration OTP (context = email) ────────────────────────────────────────

def hash_otp(otp: str, email: str) -> str:
    secret = os.environ.get("SECRET_KEY", "dev-secret-key")
    key = (secret + email.lower()).encode()
    return hmac.new(key, otp.encode(), hashlib.sha256).hexdigest()


def verify_otp_code(otp: str, email: str, stored_hash: str) -> bool:
    expected = hash_otp(otp, email)
    return hmac.compare_digest(expected, stored_hash)


# ── Login OTP (context = user_id) ─────────────────────────────────────────────

def hash_login_otp(otp: str, user_id: int) -> str:
    secret = os.environ.get("SECRET_KEY", "dev-secret-key")
    key = (secret + "login:" + str(user_id)).encode()
    return hmac.new(key, otp.encode(), hashlib.sha256).hexdigest()


def verify_login_otp_code(otp: str, user_id: int, stored_hash: str) -> bool:
    expected = hash_login_otp(otp, user_id)
    return hmac.compare_digest(expected, stored_hash)


# ── Password Reset OTP (context = user_id) ────────────────────────────────────

def hash_reset_otp(otp: str, user_id: int) -> str:
    secret = os.environ.get("SECRET_KEY", "dev-secret-key")
    key = (secret + "reset:" + str(user_id)).encode()
    return hmac.new(key, otp.encode(), hashlib.sha256).hexdigest()


def verify_reset_otp_code(otp: str, user_id: int, stored_hash: str) -> bool:
    expected = hash_reset_otp(otp, user_id)
    return hmac.compare_digest(expected, stored_hash)


# ── Shared HTTP API sender ─────────────────────────────────────────────────────

def _api_send(to_email: str, to_name: str, subject: str, html: str) -> bool:
    """Send one transactional email via Brevo HTTP API (port 443, never blocked)."""
    api_key      = os.environ.get("BREVO_API_KEY", "")
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "")
    sender_name  = os.environ.get("BREVO_SENDER_NAME", "TrintzERP")

    if not api_key:
        logger.warning("[DEV] BREVO_API_KEY not set — skipping email delivery.")
        return False

    if not sender_email:
        logger.warning("[DEV] BREVO_SENDER_EMAIL not set — skipping email delivery.")
        return False

    payload = json.dumps({
        "sender":      {"name": sender_name, "email": sender_email},
        "to":          [{"email": to_email, "name": to_name}],
        "subject":     subject,
        "htmlContent": html,
    }).encode("utf-8")

    req = urllib.request.Request(
        BREVO_API_URL,
        data=payload,
        method="POST",
        headers={
            "api-key":      api_key,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
        if status in (200, 201):
            return True
        logger.error("Brevo API returned unexpected status %s", status)
        return False
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Brevo API HTTP %s: %s", exc.code, body)
        return False
    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", to_email, exc)
        return False


# ── Public send functions ──────────────────────────────────────────────────────

def send_registration_otp(to_email: str, to_name: str, otp: str) -> bool:
    logger.warning("===== REGISTRATION OTP for %s: %s =====", to_email, otp)

    if not os.environ.get("BREVO_API_KEY"):
        logger.warning("[DEV] Email not configured — use the OTP above to verify.")
        return True

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:480px;margin:auto;background:#fff;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden">
  <div style="background:linear-gradient(135deg,#2c3e50,#3498db);padding:28px 32px">
    <h2 style="color:#fff;margin:0;font-size:20px">TrintzERP</h2>
    <p style="color:#bde0ff;margin:6px 0 0;font-size:13px">Professional Point of Sale Solution</p>
  </div>
  <div style="padding:32px">
    <h3 style="color:#2c3e50;margin-top:0">Verify Your Email Address</h3>
    <p style="color:#555;line-height:1.6">Hi <strong>{to_name}</strong>,</p>
    <p style="color:#555;line-height:1.6">
      You are registering a new account. Use the verification code below to complete your registration.
    </p>
    <div style="text-align:center;margin:28px 0">
      <div style="display:inline-block;background:#f0f7ff;border:2px solid #3498db;
                  border-radius:10px;padding:18px 36px">
        <p style="margin:0 0 6px;color:#666;font-size:12px;text-transform:uppercase;letter-spacing:1px">
          Your OTP Code
        </p>
        <p style="margin:0;font-size:38px;font-weight:700;letter-spacing:10px;
                  color:#2c3e50;font-family:monospace">{otp}</p>
      </div>
    </div>
    <p style="color:#e74c3c;font-size:13px;text-align:center">
      &#9203; This code expires in <strong>5 minutes</strong>.
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="color:#999;font-size:12px;text-align:center">
      Do not share this code with anyone.<br>
      If you did not request this, please ignore this email.
    </p>
  </div>
</div>
</body>
</html>"""

    ok = _api_send(to_email, to_name, "TrintzERP - Email Verification Code", html)
    if ok:
        logger.info("Registration OTP sent to %s", to_email)
    return ok


def send_login_otp(to_email: str, to_name: str, otp: str) -> bool:
    logger.warning("===== LOGIN OTP for %s: %s =====", to_email, otp)

    if not os.environ.get("BREVO_API_KEY"):
        logger.warning("[DEV] Email not configured — use the OTP above to verify.")
        return True

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:480px;margin:auto;background:#fff;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden">
  <div style="background:linear-gradient(135deg,#2c3e50,#e67e22);padding:28px 32px">
    <h2 style="color:#fff;margin:0;font-size:20px">TrintzERP</h2>
    <p style="color:#fde8c8;margin:6px 0 0;font-size:13px">Professional Point of Sale Solution</p>
  </div>
  <div style="padding:32px">
    <h3 style="color:#2c3e50;margin-top:0">Login Verification Code</h3>
    <p style="color:#555;line-height:1.6">Hi <strong>{to_name}</strong>,</p>
    <p style="color:#555;line-height:1.6">
      A sign-in was attempted from a new or unrecognised device. Use the code below to verify it's you.
    </p>
    <div style="text-align:center;margin:28px 0">
      <div style="display:inline-block;background:#fff8f0;border:2px solid #e67e22;
                  border-radius:10px;padding:18px 36px">
        <p style="margin:0 0 6px;color:#666;font-size:12px;text-transform:uppercase;letter-spacing:1px">
          Login Verification Code
        </p>
        <p style="margin:0;font-size:38px;font-weight:700;letter-spacing:10px;
                  color:#2c3e50;font-family:monospace">{otp}</p>
      </div>
    </div>
    <p style="color:#e74c3c;font-size:13px;text-align:center">
      &#9203; This code expires in <strong>5 minutes</strong>.
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="color:#999;font-size:12px;text-align:center">
      If you did not attempt to log in, your password may be compromised.<br>
      Do not share this code with anyone.
    </p>
  </div>
</div>
</body>
</html>"""

    ok = _api_send(to_email, to_name, "TrintzERP - Login Verification Code", html)
    if ok:
        logger.info("Login OTP sent to %s", to_email)
    return ok


def send_password_reset_otp(to_email: str, to_name: str, otp: str) -> bool:
    logger.warning("===== PASSWORD RESET OTP for %s: %s =====", to_email, otp)

    if not os.environ.get("BREVO_API_KEY"):
        logger.warning("[DEV] Email not configured — use the OTP above to reset password.")
        return True

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:480px;margin:auto;background:#fff;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden">
  <div style="background:linear-gradient(135deg,#c0392b,#e74c3c);padding:28px 32px">
    <h2 style="color:#fff;margin:0;font-size:20px">TrintzERP</h2>
    <p style="color:#fad7d7;margin:6px 0 0;font-size:13px">Password Reset Request</p>
  </div>
  <div style="padding:32px">
    <h3 style="color:#2c3e50;margin-top:0">Reset Your Password</h3>
    <p style="color:#555;line-height:1.6">Hi <strong>{to_name}</strong>,</p>
    <p style="color:#555;line-height:1.6">
      We received a request to reset your password. Use the code below to proceed.
      If you did not request this, you can safely ignore this email.
    </p>
    <div style="text-align:center;margin:28px 0">
      <div style="display:inline-block;background:#fff5f5;border:2px solid #e74c3c;
                  border-radius:10px;padding:18px 36px">
        <p style="margin:0 0 6px;color:#666;font-size:12px;text-transform:uppercase;letter-spacing:1px">
          Password Reset Code
        </p>
        <p style="margin:0;font-size:38px;font-weight:700;letter-spacing:10px;
                  color:#2c3e50;font-family:monospace">{otp}</p>
      </div>
    </div>
    <p style="color:#e74c3c;font-size:13px;text-align:center">
      &#9203; This code expires in <strong>5 minutes</strong>.
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="color:#999;font-size:12px;text-align:center">
      Never share this code with anyone — our team will never ask for it.<br>
      If you did not request a password reset, please secure your account immediately.
    </p>
  </div>
</div>
</body>
</html>"""

    ok = _api_send(to_email, to_name, "TrintzERP - Password Reset Code", html)
    if ok:
        logger.info("Password reset OTP sent to %s", to_email)
    return ok
