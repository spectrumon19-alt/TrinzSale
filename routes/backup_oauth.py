"""
backup_oauth.py — OAuth flow for Google Drive backups
Allows users to authorize TrintzPOS to access their Google Drive
and upload backups using their account (not a service account)
"""

from flask import Blueprint, request, jsonify, session, redirect, url_for
from db import get_db_connection, release_db_connection
from auth import token_required, admin_required
import os
import json
from datetime import datetime, timedelta
import hashlib
import secrets

backup_oauth_bp = Blueprint('backup_oauth', __name__)

# ── Constants ──────────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def _get_oauth_config():
    """Get OAuth credentials from environment"""
    return {
        'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID'),
        'client_secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET'),
        'redirect_uri': os.getenv('GOOGLE_OAUTH_REDIRECT_URI', 'http://localhost:5001/api/backup/oauth/callback'),
    }


def _generate_state_token():
    """Generate a secure state token for OAuth flow"""
    return secrets.token_urlsafe(32)


def _store_oauth_state(state_token):
    """Store state token temporarily (5 minutes expiry)"""
    # In production, store in Redis or database
    # For now, we'll validate immediately
    return state_token


# ── OAuth Authorization Flow ──────────────────────────────────────────────────

@backup_oauth_bp.route('/backup/oauth/authorize', methods=['POST'])
@token_required
def start_oauth_flow(payload):
    """
    Step 1: Initiate OAuth flow - return authorization URL
    User clicks this link to authorize Google Drive access
    """
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    config = _get_oauth_config()
    if not config['client_id'] or not config['client_secret']:
        return jsonify({'error': 'Google OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in environment.'}), 500

    # Generate state token for security
    state_token = _generate_state_token()
    session['oauth_state'] = state_token

    # Build authorization URL
    auth_url = (
        f"{GOOGLE_AUTH_URL}?"
        f"client_id={config['client_id']}&"
        f"redirect_uri={config['redirect_uri']}&"
        f"response_type=code&"
        f"scope={GOOGLE_DRIVE_SCOPE}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={state_token}"
    )

    return jsonify({
        'auth_url': auth_url,
        'message': 'Open this URL to authorize Google Drive access'
    }), 200


@backup_oauth_bp.route('/backup/oauth/callback', methods=['GET'])
def oauth_callback():
    """
    Step 2: Google OAuth callback - handle authorization code
    This is called by Google after user grants permission
    """
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    # Check for errors from Google
    if error:
        return f"Authorization failed: {error}", 400

    # Verify state token
    if not code or state != session.get('oauth_state'):
        return "Invalid request: state token mismatch", 400

    try:
        # Exchange authorization code for access token
        config = _get_oauth_config()
        import requests

        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                'code': code,
                'client_id': config['client_id'],
                'client_secret': config['client_secret'],
                'redirect_uri': config['redirect_uri'],
                'grant_type': 'authorization_code',
            },
            timeout=10
        )

        if token_response.status_code != 200:
            return f"Failed to get access token: {token_response.text}", 400

        token_data = token_response.json()
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in', 3600)

        if not access_token:
            return "No access token in response", 400

        # Get user info from token to identify who's authorizing
        user_info = _get_google_user_info(access_token)
        if not user_info:
            return "Failed to get user info", 400

        # Store tokens in database
        _store_oauth_tokens(access_token, refresh_token, expires_in, user_info)

        # Redirect back to backup settings with success message
        return f"""
        <html>
        <body style="font-family: Arial; padding: 40px; text-align: center;">
            <h1>✅ Authorization Successful!</h1>
            <p>Google Drive access authorized for: {user_info.get('email')}</p>
            <p>You can now close this window and return to TrintzPOS.</p>
            <p>Your backups will upload to the Google Drive folder you specify.</p>
            <script>
                window.opener.location.reload();
                window.close();
            </script>
        </body>
        </html>
        """, 200

    except Exception as e:
        return f"Error during OAuth callback: {str(e)}", 500


# ── Token Management ───────────────────────────────────────────────────────────

def _get_google_user_info(access_token):
    """Get user info from Google using access token"""
    try:
        import requests
        response = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None


def _store_oauth_tokens(access_token, refresh_token, expires_in, user_info):
    """Store OAuth tokens in backup_settings table"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Calculate expiry time
        expiry_time = datetime.utcnow() + timedelta(seconds=expires_in)

        # Store in backup_settings
        token_data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_at': expiry_time.isoformat(),
            'user_email': user_info.get('email', ''),
            'user_id': user_info.get('id', ''),
        }

        cur.execute("""
            UPDATE backup_settings SET
                oauth_enabled = TRUE,
                oauth_tokens = %s,
                oauth_user_email = %s,
                updated_at = NOW()
            WHERE id = (SELECT id FROM backup_settings LIMIT 1)
        """, (json.dumps(token_data), user_info.get('email')))

        if cur.rowcount == 0:
            # Create new record if doesn't exist
            cur.execute("""
                INSERT INTO backup_settings
                    (oauth_enabled, oauth_tokens, oauth_user_email)
                VALUES (TRUE, %s, %s)
            """, (json.dumps(token_data), user_info.get('email')))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error storing OAuth tokens: {e}")
        return False
    finally:
        cur.close()
        release_db_connection(conn)


def get_oauth_tokens():
    """Retrieve stored OAuth tokens from database"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT oauth_tokens, oauth_user_email
            FROM backup_settings
            WHERE oauth_enabled = TRUE
            LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            return None

        token_data = json.loads(row[0]) if row[0] else {}
        return token_data
    except Exception as e:
        print(f"Error retrieving OAuth tokens: {e}")
        return None
    finally:
        cur.close()
        release_db_connection(conn)


def refresh_oauth_token_if_needed():
    """Refresh OAuth token if expired"""
    tokens = get_oauth_tokens()
    if not tokens:
        return None

    # Check if token is expired
    expires_at = datetime.fromisoformat(tokens.get('expires_at', ''))
    if datetime.utcnow() < expires_at - timedelta(minutes=5):
        # Token still valid
        return tokens.get('access_token')

    # Token expired, refresh it
    try:
        config = _get_oauth_config()
        import requests

        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                'client_id': config['client_id'],
                'client_secret': config['client_secret'],
                'refresh_token': tokens.get('refresh_token'),
                'grant_type': 'refresh_token',
            },
            timeout=10
        )

        if response.status_code != 200:
            print(f"Token refresh failed: {response.text}")
            return None

        new_token_data = response.json()
        new_access_token = new_token_data.get('access_token')
        new_expires_in = new_token_data.get('expires_in', 3600)

        # Update stored tokens
        tokens['access_token'] = new_access_token
        tokens['expires_at'] = (datetime.utcnow() + timedelta(seconds=new_expires_in)).isoformat()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE backup_settings SET
                oauth_tokens = %s,
                updated_at = NOW()
            WHERE id = (SELECT id FROM backup_settings LIMIT 1)
        """, (json.dumps(tokens),))
        conn.commit()
        cur.close()
        release_db_connection(conn)

        return new_access_token
    except Exception as e:
        print(f"Error refreshing OAuth token: {e}")
        return None


# ── Status and Settings ────────────────────────────────────────────────────────

@backup_oauth_bp.route('/backup/oauth/status', methods=['GET'])
@token_required
def get_oauth_status(payload):
    """Check if OAuth is authorized and get user info"""
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    tokens = get_oauth_tokens()
    if not tokens:
        return jsonify({
            'authorized': False,
            'message': 'No OAuth authorization found'
        }), 200

    return jsonify({
        'authorized': True,
        'user_email': tokens.get('user_email'),
        'expires_at': tokens.get('expires_at'),
        'message': 'OAuth authorized'
    }), 200


@backup_oauth_bp.route('/backup/oauth/revoke', methods=['POST'])
@token_required
def revoke_oauth(payload):
    """Revoke OAuth authorization"""
    if not _admin_only(payload):
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE backup_settings SET
                oauth_enabled = FALSE,
                oauth_tokens = NULL,
                oauth_user_email = NULL,
                updated_at = NOW()
            WHERE id = (SELECT id FROM backup_settings LIMIT 1)
        """)
        conn.commit()
        return jsonify({'success': True, 'message': 'OAuth authorization revoked'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


# ── Helper ────────────────────────────────────────────────────────────────────

def _admin_only(payload):
    return payload.get('role') in ('Admin', 'Super Admin', 'Manager')
