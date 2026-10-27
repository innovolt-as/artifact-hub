"""Shared data in apps, for apps with "data": "shared" in their meta.

Without it an app's documents (window.claude.use("db"), static/hub.js) are private per user, as they always were.
With it they work like artifacts on claude.ai: every document is shared by everyone who can see the app, except
each user's own branch data/users/<e-mail>/..., which only that user can read or write (admins included).
Only admins write shared documents.

Shared documents live in the same `docs` table with owner SHARED; a branch is stored with the user's e-mail
as owner and the e-mail in lower case in the collection path.
"""
from __future__ import annotations

SHARED = "*"  # docs.owner of shared documents; never an e-mail address


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
