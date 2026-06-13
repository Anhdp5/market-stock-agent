"""
Email Sender — SMTP
====================
Sends the daily HTML report via SMTP (Office 365 / VNG mail).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List, Optional

import config

logger = logging.getLogger(__name__)


def send_report(
    html_content: str,
    plain_text:   str,
    report_date:  date,
    html_path:    Optional[Path] = None,
    recipients:   Optional[List[str]] = None,
):
    """
    Send the daily intelligence report via SMTP.

    Parameters
    ----------
    html_content : Full HTML string of the report body.
    plain_text   : Plain-text fallback.
    report_date  : Date of the report.
    html_path    : Optional path to attach the HTML file.
    recipients   : List of email addresses; defaults to config.REPORT_RECIPIENTS.
    """
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.error("SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD in .env")
        return

    recipients = recipients or config.REPORT_RECIPIENTS
    subject    = f"[Daily Market Intelligence] Market vs ZaloPay Stock - {report_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.SMTP_USER
    msg["To"]      = ", ".join(recipients)

    # Attach plain text + HTML parts
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Optionally attach the HTML file for archiving
    if html_path and html_path.exists():
        with open(html_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={html_path.name}",
        )
        msg.attach(part)

    try:
        logger.info(f"Connecting to SMTP {config.SMTP_HOST}:{config.SMTP_PORT}")
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, recipients, msg.as_string())
        logger.info(f"Report sent to: {', '.join(recipients)}")

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        raise
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        raise
