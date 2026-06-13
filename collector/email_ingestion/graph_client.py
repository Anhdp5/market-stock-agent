"""
IMAP Email Client
==================
Connects to Outlook via IMAP (SSL, port 993) and fetches emails
from a specified sender. No Azure AD or app registration required —
just your email address and password (or App Password if MFA is on).

Replaces the previous Microsoft Graph API client.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import email
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _decode_str(value: Optional[str]) -> str:
    """Decode an encoded email header string to plain text."""
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _extract_body_and_attachments(msg: Message) -> Dict[str, Any]:
    """
    Walk a MIME message and extract:
      - html_body: HTML content (preferred) or plain text
      - attachments: list of {name, content (bytes)}
    """
    html_body   = ""
    plain_body  = ""
    attachments = []

    for part in msg.walk():
        content_type        = part.get_content_type()
        content_disposition = str(part.get("Content-Disposition", ""))

        # ── Attachment ─────────────────────────────────────────────────────
        if "attachment" in content_disposition or part.get_filename():
            filename = _decode_str(part.get_filename() or "attachment")
            payload  = part.get_payload(decode=True)
            if payload:
                attachments.append({"name": filename, "content": payload})
            continue

        # ── HTML body ──────────────────────────────────────────────────────
        if content_type == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            if payload:
                charset  = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

        # ── Plain text body ────────────────────────────────────────────────
        elif content_type == "text/plain" and not plain_body:
            payload = part.get_payload(decode=True)
            if payload:
                charset    = part.get_content_charset() or "utf-8"
                plain_body = payload.decode(charset, errors="replace")

    return {
        "html_body":   html_body or plain_body,
        "attachments": attachments,
    }


class IMAPClient:
    """Thin IMAP wrapper that mimics the interface the email_parser expects."""

    def __init__(self):
        if not config.IMAP_PASSWORD:
            raise EnvironmentError(
                "IMAP credentials missing. Set IMAP_USER and IMAP_PASSWORD in .env"
            )

    def _connect(self) -> imaplib.IMAP4_SSL:
        logger.info(f"Connecting to IMAP {config.IMAP_HOST}:{config.IMAP_PORT}")
        conn = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        conn.login(config.IMAP_USER, config.IMAP_PASSWORD)
        logger.info("IMAP login successful")
        return conn

    def get_emails_from_sender(
        self,
        sender_email: str,
        since_days: int = 35,
        max_results: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Return emails from `sender_email` received in the last `since_days` days.
        Each item contains: id, subject, receivedDateTime, body (dict), hasAttachments.
        """
        since_dt  = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        search_q  = f'(FROM "{sender_email}" SINCE {since_dt})'

        conn = self._connect()
        try:
            conn.select("INBOX", readonly=True)
            status, data = conn.search(None, search_q)
            if status != "OK":
                logger.warning(f"IMAP search returned status: {status}")
                return []

            msg_ids = data[0].split()
            if not msg_ids:
                logger.info(f"No emails from {sender_email} in last {since_days} days")
                return []

            # Fetch newest first, up to max_results
            msg_ids = msg_ids[::-1][:max_results]
            logger.info(f"Found {len(msg_ids)} emails from {sender_email}")

            results = []
            for msg_id in msg_ids:
                try:
                    status, raw = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not raw or not raw[0]:
                        continue

                    raw_email = raw[0][1]
                    msg       = email.message_from_bytes(raw_email)

                    subject  = _decode_str(msg.get("Subject", ""))
                    from_hdr = _decode_str(msg.get("From", ""))
                    date_hdr = msg.get("Date", "")

                    # Parse date
                    try:
                        received_dt = email.utils.parsedate_to_datetime(date_hdr)
                        received_str = received_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception:
                        received_str = date_hdr

                    body_and_att = _extract_body_and_attachments(msg)

                    results.append({
                        "id":                  msg_id.dec