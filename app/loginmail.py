"""The login e-mail: text and HTML built from app/templates/mail/ in the hub's language.

Does not import app.main, so `python -m app.loginmail OUT_DIR` writes a preview (one .eml per language) without the
app's environment or database.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import i18n, mail

APP_DIR = Path(__file__).resolve().parent
_env = Environment(loader=FileSystemLoader(APP_DIR / "templates" / "mail"),
                   autoescape=select_autoescape(["html"]), keep_trailing_newline=True)


@dataclass
class LoginMail:
    subject: str
    text: str
    html: str
    images: dict[str, bytes]


def build(link: str, site: str, minutes: int, icon: bytes | None, lang: str | None = None) -> LoginMail:
    lang = lang or i18n.LANG
    t = partial(i18n.t_in, lang)
    subject = t("mail.subject", site=site)
    ctx = dict(t=t, lang=lang, link=link, site=site, minutes=minutes, subject=subject, has_icon=bool(icon))
    return LoginMail(
        subject=subject,
        text=_env.get_template("login.txt").render(**ctx),
        html=_env.get_template("login.html").render(**ctx),
        images={"icon": icon} if icon else {},
    )


def main(argv: list[str]) -> None:
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    site = os.environ.get("SITE_NAME", "Artifact Hub")
    try:
        icon = (APP_DIR / "static" / "apple-touch-icon.png").read_bytes()
    except OSError:
        icon = None
    for lang in i18n.available():
        m = build("https://hub.example/auth?token=preview", site, 15, icon, lang=lang)
        msg = mail.build_message("you@example.com", m.subject, m.text, html=m.html, images=m.images, sender_name=site)
        (out / f"login-{lang}.eml").write_bytes(bytes(msg))
        print(out / f"login-{lang}.eml")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m app.loginmail OUT_DIR")
    main(sys.argv)
