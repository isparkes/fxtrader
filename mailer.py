"""
Simple SMTP mailer for the FX trader daemon.

Configure via environment variables (or a .env file):

    SMTP_HOST  — SMTP server hostname       (default: smtp.gmail.com)
    SMTP_PORT  — SMTP server port           (default: 587)
    SMTP_USER  — SMTP login / sender address
    SMTP_PASS  — SMTP password / app-password
    MAIL_FROM  — From address               (default: SMTP_USER)
    MAIL_TO    — Recipient(s), comma-separated
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger("fxtrader.mailer")


def send_email(subject: str, body: str) -> bool:
    """
    Send a plain-text email using SMTP credentials from environment variables.

    Returns True on success, False on failure or misconfiguration.
    Missing credentials are warned once and the call is silently skipped.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    mail_from = os.getenv("MAIL_FROM") or smtp_user
    mail_to   = os.getenv("MAIL_TO", "")

    if not smtp_user or not smtp_pass or not mail_to:
        log.warning(
            "Email not configured — set SMTP_USER, SMTP_PASS, MAIL_TO in .env to enable alerts."
        )
        return False

    msg = MIMEMultipart()
    msg["From"]    = mail_from
    msg["To"]      = mail_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    recipients = [r.strip() for r in mail_to.split(",") if r.strip()]

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(mail_from, recipients, msg.as_string())
        log.info("Email sent: %s", subject)
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("SMTP authentication failed — check SMTP_USER / SMTP_PASS")
    except Exception as exc:
        log.error("Failed to send email: %s", exc)
    return False
