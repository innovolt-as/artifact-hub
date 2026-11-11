"""Public sharing, guest replies and the agent zone, for apps whose meta turns them on.

All three need shared data (see shared.py) and live in each user's own branch data/users/<e-mail>/, in three
zones with fixed names directly under that root:

  public/<name>[/...]   the owner reads and writes; a guest with the owner's link reads, for that <name> only
  guests/<name>[/...]   guests with the link read, create and delete their own; the owner reads unless hidden
  agent[/...]           the owner reads and writes; so does an admin through the connector

<name> is the share name the app picks (an id of a list, say), or "main" when the app shares one thing.
Everything else in the branch stays private, and the document `public` itself (id in the root collection)
is not in a zone. In an app that has not turned the matching setting on, these are ordinary collection names.

The settings are meta keys: "public": true, "public_read": [names], "guests_hidden": true, "agent": true.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
from typing import NamedTuple

from . import shared

ZONES = ("public", "guests", "agent")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # a share name, and a public_read collection name
DEFAULT_NAME = "main"


class Zone(NamedTuple):
    email: str  # the branch owner, lower case
    zone: str  # one of ZONES
    name: str | None  # the share name for public and guests, None for agent


def zone_of(collection: str) -> Zone | None:
    """The zone a stored collection path is in, or None: not in a branch, no zone name, or a bad share name."""
    segs = collection.split("/")
    if len(segs) < 4 or segs[0] != "data" or segs[1] != "users" or not segs[2] or segs[3] not in ZONES:
        return None
    email, zone = segs[2].lower(), segs[3]
    if zone == "agent":
        return Zone(email, zone, None)
    if len(segs) < 5 or not NAME_RE.match(segs[4]):
        return None
    return Zone(email, zone, segs[4])


def zone_collection(email: str, zone: str, name: str | None, rest: str = "") -> str:
    """The stored collection path of a zone, with an optional path below it."""
    parts = ["data", "users", email.lower(), zone]
    if name is not None:
        parts.append(name)
    if rest:
        parts.append(rest)
    return "/".join(parts)


def is_public(meta: dict) -> bool:
    return shared.is_shared(meta) and meta.get("public") is True


def guests_hidden(meta: dict) -> bool:
    return shared.is_shared(meta) and meta.get("guests_hidden") is True


def has_agent(meta: dict) -> bool:
    return shared.is_shared(meta) and meta.get("agent") is True


def public_read(meta: dict) -> list[str]:
    """The top-level collections a guest may read one document at a time; empty unless the app is shared."""
    names = meta.get("public_read")
    if not shared.is_shared(meta) or not isinstance(names, list):
        return []
    return [n for n in names if isinstance(n, str) and NAME_RE.match(n) and n != "data"]


# ---------------------------------------------------------------- links
class Link(NamedTuple):
    token: str
    slug: str
    owner: str  # lower case e-mail
    name: str
    title: str  # shown in the share sheet and on the settings page only
    created_at: int


def create_tables(con: sqlite3.Connection) -> None:
    """One link per app, owner and share name. The token is kept in clear so the owner can copy the link again."""
    con.execute("""CREATE TABLE IF NOT EXISTS public_links (
        token TEXT PRIMARY KEY, slug TEXT NOT NULL, owner TEXT NOT NULL, name TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, UNIQUE(slug, owner, name))""")


def get_link(con: sqlite3.Connection, slug: str, owner: str, name: str) -> Link | None:
    row = con.execute("SELECT * FROM public_links WHERE slug=? AND owner=? AND name=?",
                      (slug, owner.lower(), name)).fetchone()
    return Link(*row) if row else None


def by_token(con: sqlite3.Connection, token: str) -> Link | None:
    row = con.execute("SELECT * FROM public_links WHERE token=?", (token,)).fetchone()
    return Link(*row) if row else None


def links_of(con: sqlite3.Connection, owner: str) -> list[Link]:
    rows = con.execute("SELECT * FROM public_links WHERE owner=? ORDER BY slug, name", (owner.lower(),)).fetchall()
    return [Link(*r) for r in rows]


def make_link(con: sqlite3.Connection, slug: str, owner: str, name: str, title: str) -> Link:
    """The link for this share name, made if it does not exist; an existing one keeps its token and takes the new title."""
    owner = owner.lower()
    con.execute("INSERT OR IGNORE INTO public_links(token, slug, owner, name, title, created_at) VALUES (?,?,?,?,?,?)",
                (secrets.token_urlsafe(16), slug, owner, name, title, int(time.time())))
    con.execute("UPDATE public_links SET title=? WHERE slug=? AND owner=? AND name=?", (title, slug, owner, name))
    return get_link(con, slug, owner, name)


def rotate(con: sqlite3.Connection, slug: str, owner: str, name: str) -> Link:
    """A new token for the link, made if needed; the old token stops working at once."""
    link = get_link(con, slug, owner, name)
    if not link:
        return make_link(con, slug, owner, name, "")
    con.execute("UPDATE public_links SET token=? WHERE token=?", (secrets.token_urlsafe(16), link.token))
    return get_link(con, slug, owner, name)


def remove_link(con: sqlite3.Connection, slug: str, owner: str, name: str) -> bool:
    return con.execute("DELETE FROM public_links WHERE slug=? AND owner=? AND name=?",
                       (slug, owner.lower(), name)).rowcount > 0


def rename(con: sqlite3.Connection, old: str, new: str) -> None:
    con.execute("UPDATE OR REPLACE public_links SET slug=? WHERE slug=?", (new, old))


def delete_owner(con: sqlite3.Connection, owner: str) -> None:
    con.execute("DELETE FROM public_links WHERE owner=?", (owner.lower(),))


def count_links(con: sqlite3.Connection, slug: str) -> int:
    return con.execute("SELECT COUNT(*) FROM public_links WHERE slug=?", (slug,)).fetchone()[0]
