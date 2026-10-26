"""Who may see an app, and who may log in.

An app's access lives in its meta (meta.json, <slug>.meta.json or the .link.json itself):
    "admin_only": true             -> only admins ("Bare meg"); always wins
    "access": "people"             -> admins and the e-mails in "people" ("Bestemte personer")
    neither                        -> everyone who can log in ("Alle")
The "people" list stays in the meta when the level changes, so it comes back when "people" is chosen again.

Invited e-mails (the "Personer" list on the admin page) are kept in the db table `invites` and may log in.
"""
from __future__ import annotations

import sqlite3
import time

from app.i18n import t, tn

LEVELS = ("all", "people", "admin")
_ICONS = {"all": "🌍", "people": "👥", "admin": "🔒"}


def norm(email: str) -> str:
    return email.strip().lower()


def level(meta: dict) -> str:
    if meta.get("admin_only"):
        return "admin"
    return "people" if meta.get("access") == "people" else "all"


def _clean(emails) -> list[str]:
    """Normalised, without duplicates, in the order given; anything that is not a string is dropped."""
    out: list[str] = []
    for e in emails or []:
        if isinstance(e, str) and norm(e) and norm(e) not in out:
            out.append(norm(e))
    return out


def people(meta: dict) -> list[str]:
    return _clean(meta.get("people"))


def can_see(meta: dict, email: str | None, admin: bool) -> bool:
    if admin:
        return True
    lvl = level(meta)
    if lvl == "all":
        return True
    return lvl == "people" and bool(email) and norm(email) in people(meta)


def set_level(meta: dict, level: str, people: list[str] | None = None) -> None:
    """Change `meta` in place. people=None leaves the list alone; an empty list removes it."""
    if level not in LEVELS:
        raise ValueError(t("access.unknown", level=level))
    if people is not None:
        cleaned = _clean(people)
        if cleaned:
            meta["people"] = cleaned
        else:
            meta.pop("people", None)
    if level == "admin":
        meta["admin_only"] = True
        meta.pop("access", None)
    else:
        meta.pop("admin_only", None)
        if level == "people":
            meta["access"] = "people"
        else:
            meta.pop("access", None)


def describe(meta: dict) -> str:
    lvl = level(meta)
    if lvl == "all":
        return t("access.all")
    if lvl == "admin":
        return t("access.admin")
    n = len(people(meta))
    return tn("access.people", n)


def label(meta: dict) -> str:
    text = describe(meta)
    return f"{_ICONS[level(meta)]} {text[:1].upper()}{text[1:]}"


# ---------------------------------------------------------------- invited people (may log in)
def create_tables(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS invites(email TEXT PRIMARY KEY, at INTEGER NOT NULL)")


def invite(con: sqlite3.Connection, email: str, now: int | None = None) -> None:
    con.execute("INSERT OR IGNORE INTO invites(email, at) VALUES(?,?)", (norm(email), int(now or time.time())))


def uninvite(con: sqlite3.Connection, email: str) -> None:
    con.execute("DELETE FROM invites WHERE email=?", (norm(email),))


def invited(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT email FROM invites ORDER BY email")]


def is_invited(con: sqlite3.Connection, email: str) -> bool:
    return con.execute("SELECT 1 FROM invites WHERE email=?", (norm(email),)).fetchone() is not None
