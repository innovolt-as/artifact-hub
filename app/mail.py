"""E-mail sending for the hub.

To add an API-based provider (Resend, Postmark, SES): implement `send()` for it here and pick it from an env var.
This is the only place the hub sends e-mail.

Contract: `send(to, subject, text, html=None, images=None, sender_name=None) -> bool`.
  - `text` is the plain-text body; `html`, when given, is sent as the alternative. `images` maps a Content-ID name to
    PNG bytes, attached inline to the HTML part (reference them as `cid:<name>`).
  - `sender_name` becomes the display name when SMTP_FROM is only an address (a name already in SMTP_FROM wins).
  - Returns False only when no provider is configured (the hub then logs the login link instead). When a send fails
    it must raise, otherwise magic links would be logged with a misleading message.
Use `build_message()` to get the same message a provider should send.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "hub@localhost")
SMTP_TLS = os.environ.get("SMTP_TLS", "starttls")  # starttls | ssl | none


def configured() -> bool:
    return bool(SMTP_HOST)


def sender(sender_name: str | None) -> str:
    """SMTP_FROM unchanged if it has a name (or there is no sender_name); otherwise `sender_name <address>`."""
    name, address = parseaddr(SMTP_FROM)
    if name or not sender_name:
        return SMTP_FROM
    return formataddr((sender_name, address))


def _domain() -> str:
    address = parseaddr(SMTP_FROM)[1]
    return address.rpartition("@")[2] if "@" in address else "localhost"


def build_message(to: str, subject: str, text: str, html: str | None = None,
                  images: dict[str, bytes] | None = None, sender_name: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender(sender_name)
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_domain())
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
        for name, data in (images or {}).items():
            msg.get_payload()[1].add_related(data, "image", "png", cid=f"<{name}>")
    return msg


def send(to: str, subject: str, text: str, html: str | None = None,
         images: dict[str, bytes] | None = None, sender_name: str | None = None) -> bool:
    """Send a mail. Returns False (and does nothing) when no mail server is configured."""
    if not configured():
        return False
    msg = build_message(to, subject, text, html, images, sender_name)
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
