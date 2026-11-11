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
