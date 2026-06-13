"""
IMAP Email Client
==================
Connects to Outlook via IMAP (SSL, port 993).
No Azure AD or app registration required.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import email
import imaplib
import logging
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Any, Dict, List

import config

logger = logging.getLogger(__name__)


def _decode_str(value):
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


def _extract_body_and_attachments(msg):
    html_body   = ""
    plain_body  = ""
    attachments = []

    for part in msg.walk():
        content_type        = part.get_content_type()
        content_disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in content_disposition or part.get_filename():
            filename = _decode_str(part.get_filename() or "attachment")
            payload  = part.get_payload(decode=True)
            if payload:
                attachments.append({"name": filename, "content": payload})
            continue

        if content_type == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            if payload:
                charset   = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

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

    def __init__(self):
        if not config.IMAP_PASSWORD:
            raise EnvironmentError(
                "IMAP credentials missing. Set IMAP_USER and IMAP_PASSWORD in .env"
            )

    def _connect(self):
        logger.info("Connecting to IMAP {}:{}".format(config.IMAP_HOST, config.IMAP_PORT))
        conn = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        conn.login(config.IMAP_USER, config.IMAP_PASSWORD)
        logger.info("IMAP login successful")
        return conn

    def get_emails_from_sender(self, sender_email, since_days=35, max_results=200):
        since_dt = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        search_q = '(FROM "{}" SINCE {})'.format(sender_email, since_dt)

        conn = self._connect()
        try:
            conn.select("INBOX", readonly=True)
            status, data = conn.search(None, search_q)
            if status != "OK":
                logger.warning("IMAP search status: {}".format(status))
                return []

            msg_ids = data[0].split()
            if not msg_ids:
                logger.info("No emails from {} in last {} days".format(sender_email, since_days))
                return []

            msg_ids = msg_ids[::-1][:max_results]
            logger.info("Found {} emails from {}".format(len(msg_ids), sender_email))

            results = []
            for msg_id in msg_ids:
                try:
                    status, raw = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not raw or not raw[0]:
                        continue

                    msg      = email.message_from_bytes(raw[0][1])
                    subject  = _decode_str(msg.get("Subject", ""))
                    date_hdr = msg.get("Date", "")

                    try:
                        received_dt  = email.utils.parsedate_to_datetime(date_hdr)
                        received_str = received_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception:
                        received_str = date_hdr

                    body_and_att = _extract_body_and_attachments(msg)

                    results.append({
                        "id":               msg_id.decode(),
                        "subject":          subject,
                        "receivedDateTime": received_str,
                        "hasAttachments":   len(body_and_att["attachments"]) > 0,
                        "body":             {"content": body_and_att["html_body"]},
                        "_attachments":     body_and_att["attachments"],
                    })
                except Exception as e:
                    logger.warning("Failed to parse message {}: {}".format(msg_id, e))

            logger.info("Parsed {} emails".format(len(results)))
            return results

        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def list_attachments(self, message_id):
        return []

    def get_attachment_content(self, message_id, attachment_id):
        return b""
