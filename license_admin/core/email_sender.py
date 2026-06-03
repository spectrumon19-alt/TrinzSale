"""
email_sender.py — Unified email interface using Brevo MCP server.

All emails are sent via the Brevo REST API through the MCP protocol.
No SMTP, no external dependencies — pure Brevo API v3.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_email(
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> dict:
    """
    Send an email via Brevo MCP server.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html: HTML email body
        text: Plain text email body (optional, auto-generates if not provided)
        attachment_path: Path to file to attach (optional)
        attachment_name: Name for the attachment (optional, defaults to filename)

    Returns:
        {'success': bool, 'message_id': str, 'error': str}
    """
    from core.brevo_mcp import get_mcp

    # Get the global MCP server
    mcp = get_mcp()

    # Build attachments list
    attachments = None
    if attachment_path:
        attachments = [{"path": attachment_path, "name": attachment_name}]

    # Send via MCP
    result = mcp.send_email(
        to_email=to_email,
        subject=subject,
        html_content=html,
        text_content=text,
        attachments=attachments,
    )

    return result
