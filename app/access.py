"""Who may see an app, and who may log in.

An app's access lives in its meta (meta.json, <slug>.meta.json or the .link.json itself):
    "admin_only": true             -> only admins ("Bare meg"); always wins
    "access": "people"             -> admins and the e-mails in "people" ("Bestemte personer")
    neither                        -> everyone who can log in ("Alle")
The "people" list stays in the meta when the level changes, so it comes back when "people" is chosen again.

Invited e-mails (the "Personer" list on the admin page) are kept in the db table `invites` and may log in.
"""
from __future__ import annotations

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
        raise ValueError(f"Ukjent tilgang: {level}")
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
        return "alle"
    if lvl == "admin":
        return "bare meg"
    n = len(people(meta))
    return "1 person" if n == 1 else f"{n} personer"


def label(meta: dict) -> str:
    text = describe(meta)
    return f"{_ICONS[level(meta)]} {text[:1].upper()}{text[1:]}"
