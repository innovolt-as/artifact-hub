"""E-mail sending for the hub.

To add an API-based provider (Resend, Postmark, SES): implement `send()` for it here and pick it from an env var.
This is the only place the hub sends e-mail.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "hub@localhost")
SMTP_TLS = os.environ.get("SMTP_TLS", "starttls")  # starttls | ssl | none


def configured() -> bool:
    return bool(SMTP_HOST)


def send(to: str, subject: str, body: str) -> bool:
    """Send a plain-text mail. Returns False (and does nothing) when no mail server is configured."""
    if not configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg.set_content(body)
    if SMTP_TLS == "ssl":
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        if SMTP_TLS == "starttls":
            server.starttls()
    with server:
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    return True
