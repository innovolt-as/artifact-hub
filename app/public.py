"""Public sharing, guest replies and the agent zone, for apps whose meta turns them on.

All three need shared data (see shared.py) and live in each user's own branch data/users/<e-mail>/, in three
zones with fixed names directly under that root:

  public/<name>[/...]   the owner reads and writes; a guest with the owner's link reads, for that <name> only
  guests/<name>[/...]   guests with the link read, create and delete their own; the owner reads unless hidden
  agent[/...]           the owner reads and writes; so does an admin through the connector

<name> is the share name the app picks (an id of a list, say), or "main" when the app shares one thing.
Everything else in the branch stays private, and the document `public` itself (id in the root collection)
is not in a zone. In an app that has not turned the matching setting on, these are ordinary collection names; the
guests zone counts as a zone while "public" or "guests_hidden" is on.

The settings are meta keys: "public": true, "public_read": [names], "guests_hidden": true, "agent": true.

A guest proves which guest documents are theirs with a secret of their own (hub.js keeps it in localStorage); the
hub stores only its hash, in the field _guest, which no reader is ever shown.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
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


def delete_slug(con: sqlite3.Connection, slug: str) -> None:
    con.execute("DELETE FROM public_links WHERE slug=?", (slug,))


def delete_owner(con: sqlite3.Connection, owner: str) -> None:
    con.execute("DELETE FROM public_links WHERE owner=?", (owner.lower(),))


def count_links(con: sqlite3.Connection, slug: str) -> int:
    return con.execute("SELECT COUNT(*) FROM public_links WHERE slug=?", (slug,)).fetchone()[0]


# ---------------------------------------------------------------- guests
GUEST_SECRET_RE = re.compile(r"[\x21-\x7e]{16,128}")  # the X-Hub-Guest header: printable ASCII, no spaces
# Fields only the hub sets: _guest (the secret's hash, shown to no one), _mine (added to what a guest reads) and the
# stamp of shared.py. A guest's own values for them are dropped; what each reader gets of them is decided below.
HUB_FIELDS = ("_guest", "_mine", *shared.STAMP_KEYS)
GUEST_WRITES_PER_IP = 30          # per hour
GUEST_WRITES_PER_LINK = 200       # per hour
GUEST_WINDOW = 3600
_guest_writes: dict[str, list[float]] = {}  # "ip:<ip>" and "link:<token>" -> times of recent writes
_guest_lock = threading.Lock()


def guest_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def in_guest_zone(meta: dict, collection: str) -> bool:
    """Whether a stored collection is in a guests zone of an app with public sharing or guests_hidden on. The rules
    hold while either is: with only "public" turned off, hidden replies stay hidden and guest-only."""
    zone = zone_of(collection)
    return zone is not None and zone.zone == "guests" and (is_public(meta) or guests_hidden(meta))


def guest_input(data: dict, secret_hash: str, now: int) -> dict:
    """The guest document to store: the guest's fields, and the hub's _guest and _added_at."""
    out = {k: v for k, v in data.items() if k not in HUB_FIELDS}
    out.update(_guest=secret_hash, _added_at=now)
    return out


def guest_view(data: dict, zone: str, secret_hash: str | None) -> dict:
    """A document of the public or guests zone as a guest reads it: no _guest, no _added_by, and in the guests zone
    _mine for the guest who made it. _added_at stays: in the guests zone it is the hub's."""
    out = {k: v for k, v in data.items() if k not in HUB_FIELDS or k == "_added_at"}
    if zone == "guests":
        out["_mine"] = guest_owns(data, secret_hash)
    return out


def shared_view(data: dict) -> dict:
    """A document of a public_read collection as a guest reads it: none of the hub's fields."""
    return {k: v for k, v in data.items() if k not in HUB_FIELDS}


def owner_view(data: dict) -> dict:
    """A guest document as a logged-in reader (its owner) gets it: everything but _guest."""
    return {k: v for k, v in data.items() if k != "_guest"}


def guest_owns(data: dict, secret_hash: str | None) -> bool:
    """Whether a stored guest document was made with the secret of this hash; never for a missing or foreign _guest."""
    stored = data.get("_guest")
    if not secret_hash or not isinstance(stored, str):
        return False
    return hmac.compare_digest(stored.encode("utf-8"), secret_hash.encode("utf-8"))


def _recent(key: str, now: float) -> list[float]:
    recent = [t for t in _guest_writes.get(key, []) if now - t < GUEST_WINDOW]
    if recent:
        _guest_writes[key] = recent
    else:
        _guest_writes.pop(key, None)
    return recent


def _limited(ip: str, token: str, now: float) -> bool:
    return (len(_recent(f"ip:{ip}", now)) >= GUEST_WRITES_PER_IP
            or len(_recent(f"link:{token}", now)) >= GUEST_WRITES_PER_LINK)


def _count(ip: str, token: str, now: float) -> None:
    if len(_guest_writes) > 10000:  # drop expired keys, then the oldest if still too many
        for key in list(_guest_writes):
            _recent(key, now)
        if len(_guest_writes) > 10000:
            for key in sorted(_guest_writes, key=lambda k: _guest_writes[k][-1])[:5000]:
                del _guest_writes[key]
    for key in (f"ip:{ip}", f"link:{token}"):
        _guest_writes[key] = _recent(key, now) + [now]


def guest_limited(ip: str, token: str, now: float) -> bool:
    """Whether a guest write from this IP on this link would go over a rate limit; counts nothing (guest_count does)."""
    with _guest_lock:
        return _limited(ip, token, now)


def guest_count(ip: str, token: str, now: float) -> None:
    """Count one guest write from this IP on this link."""
    with _guest_lock:
        _count(ip, token, now)


def guest_try(ip: str, token: str, now: float) -> bool:
    """guest_limited and guest_count under one lock: False over a rate limit, else True with the write counted."""
    with _guest_lock:
        if _limited(ip, token, now):
            return False
        _count(ip, token, now)
        return True
