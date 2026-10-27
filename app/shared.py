"""Shared data in apps, for apps with "data": "shared" in their meta.

Without it an app's documents (window.claude.use("db"), static/hub.js) are private per user, as they always were.
With it they work like artifacts on claude.ai: every document is shared by everyone who can see the app, except
each user's own branch data/users/<e-mail>/..., which only that user can read or write (admins included).
Only admins write shared documents.

Shared documents live in the same `docs` table with owner SHARED; a branch is stored with the user's e-mail
as owner and the e-mail in lower case in the collection path.

The table claude_writes notes when the connector last wrote data in an app, per user. The admin page uses it
to warn about an app that Claude fills with an admin's personal data while others can see it.
"""
from __future__ import annotations

import sqlite3
import time

SHARED = "*"  # docs.owner of shared documents; never an e-mail address
CLAUDE_DAYS = 30  # a connector write this recent counts for the admin warning


def is_shared(meta: dict) -> bool:
    return meta.get("data") == "shared"


def _branch(collection: str) -> list[str] | None:
    """The segments of a data/users/<e-mail>[/...] collection, or None when it is not inside a branch."""
    segs = collection.split("/")
    return segs if len(segs) >= 3 and segs[0] == "data" and segs[1] == "users" else None


def normalize(collection: str) -> str:
    """The collection as stored: the e-mail of a branch in lower case, anything else as it is."""
    segs = _branch(collection)
    if not segs:
        return collection
    return "/".join([*segs[:2], segs[2].lower(), *segs[3:]])


def branch_owner(collection: str, user: str) -> str | None:
    """In a shared app: the docs.owner for a collection. SHARED, the user for their own branch,
    or None for someone else's branch (reads find nothing, writes are refused)."""
    segs = _branch(collection)
    if not segs:
        return SHARED
    return user.lower() if segs[2].lower() == user.lower() else None


def own_prefix(user: str) -> str:
    """The collection of a user's own branch; everything under it starts with this plus '/'."""
    return f"data/users/{user.lower()}"


# ---------------------------------------------------------------- connector writes (the admin warning)
def create_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS claude_writes(
             slug  TEXT NOT NULL,
             email TEXT NOT NULL,
             at    INTEGER NOT NULL,
             PRIMARY KEY (slug, email))"""
    )


def record_write(con: sqlite3.Connection, slug: str, email: str, now: int | None = None) -> None:
    con.execute(
        """INSERT INTO claude_writes(slug, email, at) VALUES(?,?,?)
           ON CONFLICT(slug, email) DO UPDATE SET at=excluded.at""",
        (slug, email.lower(), int(now if now is not None else time.time())),
    )


def recent_admin_writes(con: sqlite3.Connection, admins: set[str], now: int | None = None) -> set[str]:
    """Apps an admin wrote data in through the connector within the last CLAUDE_DAYS days."""
    if not admins:
        return set()
    since = int(now if now is not None else time.time()) - CLAUDE_DAYS * 86400
    marks = ",".join("?" * len(admins))
    rows = con.execute(f"SELECT DISTINCT slug FROM claude_writes WHERE at >= ? AND email IN ({marks})",
                       (since, *sorted(admins))).fetchall()
    return {r[0] for r in rows}


def rename(con: sqlite3.Connection, old: str, new: str) -> None:
    con.execute("UPDATE OR REPLACE claude_writes SET slug=? WHERE slug=?", (new, old))
