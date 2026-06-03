"""
Brevo Email MCP Server — Model Context Protocol interface for email sending.

Implements Brevo REST API v3 (/v3/smtp/email) as an MCP resource server.
Provides a clean interface for sending emails with attachments.
"""

import json
import base64
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

BREVO_API_BASE = "https://api.brevo.com/v3"
BREVO_EMAIL_ENDPOINT = f"{BREVO_API_BASE}/smtp/email"


class BrevoMCPServer:
    """MCP server for Brevo email API."""

    def __init__(self, api_key: str, sender_email: str, sender_name: str = "TrintzPOS"):
        """
        Initialize the Brevo MCP server.

        Args:
            api_key: Brevo REST API key (xkeysib-...)
            sender_email: Sender email address (must be verified in Brevo)
            sender_name: Sender display name
        """
        if not api_key:
            raise ValueError("BREVO_API_KEY is required")
        if not sender_email:
            raise ValueError("Sender email is required")

        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self._verify_config()

    def _verify_config(self) -> None:
        """Verify the API key and sender are valid by checking account info."""
        try:
            req = Request(
                f"{BREVO_API_BASE}/account",
                headers={"api-key": self.api_key, "Accept": "application/json"},
                method="GET",
            )
            with urlopen(req, timeout=10) as resp:
                account = json.loads(resp.read().decode())
                logger.info(f"Brevo account verified: {account.get('email')}")
        except Exception as e:
            logger.warning(f"Could not verify Brevo account: {e}")

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Brevo REST API.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email body
            text_content: Plain text email body (optional)
            attachments: List of {'path': str, 'name': str} dicts (optional)

        Returns:
            {'success': bool, 'message_id': str, 'error': str}
        """
        if not to_email:
            return {"success": False, "error": "Recipient email is required"}
        if not subject:
            return {"success": False, "error": "Subject is required"}
        if not html_content:
            return {"success": False, "error": "HTML content is required"}

        # Build payload
        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        }

        if text_content:
            payload["textContent"] = text_content

        # Handle attachments
        if attachments:
            payload["attachment"] = []
            for att in attachments:
                att_path = att.get("path")
                att_name = att.get("name")

                if not att_path:
                    return {"success": False, "error": "Attachment path is required"}

                p = Path(att_path)
                if not p.exists():
                    return {"success": False, "error": f"File not found: {att_path}"}

                size_mb = p.stat().st_size / 1_048_576
                if size_mb > 10:
                    return {
                        "success": False,
                        "error": f"Attachment {att_name or p.name} is {size_mb:.1f} MB (max 10 MB)",
                    }

                # Determine MIME type from file extension
                name = att_name or p.name
                ext = p.suffix.lower()
                mime_type = {
                    ".zip": "application/zip",
                    ".pdf": "application/pdf",
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".txt": "text/plain",
                }.get(ext, "application/octet-stream")

                payload["attachment"].append(
                    {
                        "content": base64.b64encode(p.read_bytes()).decode("ascii"),
                        "name": name,
                        "mimeType": mime_type,
                    }
                )

        # Send request
        return self._send_request(payload, to_email)

    def _send_request(self, payload: Dict[str, Any], to_email: str) -> Dict[str, Any]:
        """Send HTTP request to Brevo API."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(
                BREVO_EMAIL_ENDPOINT,
                data=data,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            with urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201, 202):
                    body = json.loads(resp.read().decode("utf-8") or "{}")
                    message_id = body.get("messageId", "")
                    logger.info(f"Email sent to {to_email}: {message_id}")
                    return {"success": True, "message_id": message_id}

                return {"success": False, "error": f"API returned {resp.status}"}

        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            logger.error(f"Brevo API {e.code}: {body}")
            try:
                # Try to parse as JSON
                if body.strip().startswith('{'):
                    err = json.loads(body)
                    error_msg = err.get("message", body)
                else:
                    # If not JSON, it's likely an HTML error page
                    if '<' in body:
                        error_msg = f"Server error ({e.code}). Check API key and sender email verification."
                    else:
                        error_msg = body
            except json.JSONDecodeError:
                error_msg = f"Server error ({e.code}). Check API key and sender email verification."
            return {"success": False, "error": error_msg}

        except URLError as e:
            logger.error(f"Connection error: {e.reason}")
            return {"success": False, "error": f"Connection error: {e.reason}"}

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {"success": False, "error": str(e)}


# Global MCP server instance
_mcp_server: Optional[BrevoMCPServer] = None


def init_mcp(api_key: str, sender_email: str, sender_name: str = "TrintzPOS") -> BrevoMCPServer:
    """Initialize the global MCP server."""
    global _mcp_server
    _mcp_server = BrevoMCPServer(api_key, sender_email, sender_name)
    return _mcp_server


def get_mcp() -> BrevoMCPServer:
    """Get the global MCP server instance."""
    global _mcp_server
    if not _mcp_server:
        from config import Config
        _mcp_server = BrevoMCPServer(
            Config.BREVO_API_KEY,
            Config.BREVO_SENDER_EMAIL,
            Config.BREVO_SENDER_NAME,
        )
    return _mcp_server
