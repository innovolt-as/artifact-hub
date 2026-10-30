"""Front page data, per logged-in user: which apps they have chosen for it, which apps they have seen in the
"Velg apper" list, which apps they open, what they pin, how they view the list, and the one-line summary each
app can leave for its card.

Everything takes an open connection from main.db() (rows as sqlite3.Row) and an e-mail; nothing here
is shared between users, except the summary line of apps with shared data (app/shared.py).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app import i18n
from app.shared import SHARED

DAY = 86400
MOST_USED_DAYS = 30    # what counts towards "Mest brukt"
KEEP_DAYS = 90         # visits older than this are deleted
REVISIT_GAP = 600      # opening the same app again within 10 minutes (reloads) is not a new visit
MOST_USED_MAX = 4
STATS_DAYS = 7         # the admin statistics cover the last week
SUMMARY_MAX = 140
VIEWS = ("icons", "cards")
THEMES = ("auto", "light", "dark")
SUMMARY_DOC = ("hub", "summary")      # db.doc("hub/summary") in apps using window.claude.use("db")
SUMMARY_KEY = "hub/summary"           # /api/data/<slug>/hub/summary in apps using the data API


def create_tables(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS visits(email TEXT NOT NULL, slug TEXT NOT NULL, at INTEGER NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS visits_email_at ON visits(email, at)")
    con.execute(
        """CREATE TABLE IF NOT EXISTS prefs(
             email TEXT NOT NULL,
             key   TEXT NOT NULL,
             value TEXT NOT NULL,
             PRIMARY KEY (email, key))"""
    )


# ---------------------------------------------------------------- visits
def record_visit(con: sqlite3.Connection, email: str, slug: str, now: int | None = None) -> None:
    now = int(now if now is not None else time.time())
    email = email.lower()
    if con.execute(
        "SELECT 1 FROM visits WHERE email=? AND slug=? AND at>?", (email, slug, now - REVISIT_GAP)
    ).fetchone():
        return
    con.execute("INSERT INTO visits(email, slug, at) VALUES(?,?,?)", (email, slug, now))
    con.execute("DELETE FROM visits WHERE email=? AND at<?", (email, now - KEEP_DAYS * DAY))


def visit_stats(con: sqlite3.Connection, email: str, now: int | None = None) -> dict[str, dict]:
    """{slug: {"count": opens in the last 30 days, "last": latest open}}."""
    now = int(now if now is not None else time.time())
    rows = con.execute(
        "SELECT slug, SUM(at >= ?) AS count, MAX(at) AS last FROM visits WHERE email=? GROUP BY slug",
        (now - MOST_USED_DAYS * DAY, email.lower()),
    ).fetchall()
    return {r["slug"]: {"count": int(r["count"] or 0), "last": int(r["last"])} for r in rows}


def week_stats(con: sqlite3.Connection, exclude=(), now: int | None = None) -> dict:
    """App opens in the last 7 days, for the admin statistics: who is active and which apps are used.

    {"opens": total, "users": [{"email", "opens", "last", "apps": [(slug, opens)]}],
     "apps": [{"slug", "opens", "users": [(email, opens)]}]}, both lists most opens first (ties: A-Z).
    `exclude` (the admins) is left out."""
    now = int(now if now is not None else time.time())
    rows = con.execute(
        "SELECT email, slug, COUNT(*) AS n, MAX(at) AS last FROM visits WHERE at >= ? GROUP BY email, slug",
        (now - STATS_DAYS * DAY,),
    ).fetchall()
    rows = [r for r in rows if r["email"] not in {e.lower() for e in exclude}]
    users: dict[str, dict] = {}
    apps: dict[str, dict] = {}
    for r in rows:
        u = users.setdefault(r["email"], {"email": r["email"], "opens": 0, "last": 0, "apps": []})
        u["opens"] += r["n"]
        u["last"] = max(u["last"], r["last"])
        u["apps"].append((r["slug"], r["n"]))
        a = apps.setdefault(r["slug"], {"slug": r["slug"], "opens": 0, "users": []})
        a["opens"] += r["n"]
        a["users"].append((r["email"], r["n"]))
    for u in users.values():
        u["apps"].sort(key=lambda pair: (-pair[1], pair[0]))
    for a in apps.values():
        a["users"].sort(key=lambda pair: (-pair[1], pair[0]))
    return {
        "opens": sum(u["opens"] for u in users.values()),
        "users": sorted(users.values(), key=lambda u: (-u["opens"], u["email"])),
        "apps": sorted(apps.values(), key=lambda a: (-a["opens"], a["slug"])),
    }


# ---------------------------------------------------------------- prefs
def _get(con: sqlite3.Connection, email: str, key: str, default):
    row = con.execute("SELECT value FROM prefs WHERE email=? AND key=?", (email.lower(), key)).fetchone()
    return json.loads(row["value"]) if row else default


def _put(con: sqlite3.Connection, email: str, key: str, value) -> None:
    con.execute(
        "INSERT INTO prefs(email, key, value) VALUES(?,?,?) ON CONFLICT(email, key) DO UPDATE SET value=excluded.value",
        (email.lower(), key, json.dumps(value)),
    )


def _slugs(value) -> list[str]:
    return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []


def get_prefs(con: sqlite3.Connection, email: str) -> dict:
    """view, pins, apps (chosen for the front page; [] when never chosen), seen (None until the list
    has been opened) and tz (the viewer's time zone, None until the browser has told us)."""
    view = _get(con, email, "view", "icons")
    seen = _get(con, email, "seen", None)
    tz = _get(con, email, "tz", None)
    return {"view": view if view in VIEWS else "icons", "pins": _slugs(_get(con, email, "pins", [])),
            "apps": _slugs(_get(con, email, "apps", [])), "seen": None if seen is None else _slugs(seen),
            "tz": tz if isinstance(tz, str) else None}


def set_view(con: sqlite3.Connection, email: str, view: str) -> None:
    if view not in VIEWS:
        raise ValueError(i18n.t("err.unknown_view", view=view))
    _put(con, email, "view", view)


def get_theme(con: sqlite3.Connection, email: str) -> str:
    """The viewer's chosen theme; "auto" (follow the device) when never chosen or the stored value is unknown."""
    try:
        theme = _get(con, email, "theme", "auto")
    except ValueError:  # the stored text is not JSON
        return "auto"
    return theme if theme in THEMES else "auto"


def set_theme(con: sqlite3.Connection, email: str, theme: str) -> None:
    if theme not in THEMES:
        raise ValueError(i18n.t("err.unknown_theme", theme=theme))
    _put(con, email, "theme", theme)


def set_tz(con: sqlite3.Connection, email: str, tz: str) -> None:
    """Remember the viewer's IANA time zone (e.g. "Europe/Oslo"); ValueError if it is not one."""
    try:
        if not isinstance(tz, str) or len(tz) > 64:
            raise ValueError(tz)
        ZoneInfo(tz)
    except (ValueError, OSError, KeyError):  # an unknown zone is a KeyError, a directory like "Europe" an OSError
        raise ValueError(i18n.t("err.unknown_tz", tz=tz)) from None
    _put(con, email, "tz", tz)


def set_pin(con: sqlite3.Connection, email: str, slug: str, pinned: bool) -> list[str]:
    pins = [p for p in get_prefs(con, email)["pins"] if p != slug]
    if pinned:
        pins.append(slug)
    _put(con, email, "pins", pins)
    return pins


def set_pin_order(con: sqlite3.Connection, email: str, order: list[str]) -> list[str]:
    """Reorder the pins: pinned slugs in `order` first (no duplicates, unknown ones ignored), then the
    pinned slugs `order` left out, in their old order."""
    old = get_prefs(con, email)["pins"]
    pins = [s for s in dict.fromkeys(order) if s in old]
    pins += [s for s in old if s not in pins]
    _put(con, email, "pins", pins)
    return pins


# ---------------------------------------------------------------- the apps each user has chosen
def start(con: sqlite3.Connection, email: str, visible: list[str], *, admin: bool) -> None:
    """The first time: an admin gets every app they can see (their front page looks as before); anyone
    else starts with an empty front page, so nothing is stored for them."""
    if admin and _get(con, email, "apps", None) is None:
        _put(con, email, "apps", list(visible))
        _put(con, email, "seen", list(visible))


def mark_seen(con: sqlite3.Connection, email: str, slugs: list[str]) -> None:
    seen = get_prefs(con, email)["seen"] or []
    _put(con, email, "seen", seen + [s for s in slugs if s not in seen])


def set_added(con: sqlite3.Connection, email: str, slug: str, added: bool) -> list[str]:
    apps = [a for a in get_prefs(con, email)["apps"] if a != slug]
    if added:
        apps.append(slug)
    _put(con, email, "apps", apps)
    mark_seen(con, email, [slug])
    return apps


def add_for(con: sqlite3.Connection, emails, slug: str) -> None:
    """Put a brand-new app on these users' front pages (admins). Users who have never had choices stored
    get it anyway through start()."""
    for email in emails:
        if _get(con, email, "apps", None) is not None and slug not in get_prefs(con, email)["apps"]:
            set_added(con, email, slug, True)


def rename(con: sqlite3.Connection, old: str, new: str) -> None:
    """An app got a new address: it stays chosen, pinned and seen for everyone."""
    for row in con.execute("SELECT email, key, value FROM prefs WHERE key IN ('apps', 'seen', 'pins')").fetchall():
        value = json.loads(row["value"])
        if isinstance(value, list) and old in value:
            _put(con, row["email"], row["key"], [new if s == old else s for s in value if s != new])


def picker(apps: list[dict], chosen: list[str], seen: list[str] | None) -> list[dict]:
    """The "Velg apper" list: marks each app added/unseen; unseen first, each group in the given order.

    Unseen = came after the user last opened the list. Before the first opening nothing is unseen, and an
    app on the front page always counts as seen."""
    for a in apps:
        a["added"] = a["slug"] in chosen
        a["unseen"] = seen is not None and not a["added"] and a["slug"] not in seen
    return [a for a in apps if a["unseen"]] + [a for a in apps if not a["unseen"]]


# ---------------------------------------------------------------- summaries
def card_line(text: object) -> str | None:
    """The line a card shows for `text` (a recipe's result or a stored summary): trimmed and cut at SUMMARY_MAX
    characters; None when that leaves nothing or it is not a string."""
    if not isinstance(text, str):
        return None
    return text.strip()[:SUMMARY_MAX] or None


def _text(raw: str) -> str | None:
    try:
        text = json.loads(raw).get("text")
    except (ValueError, AttributeError):
        return None
    return card_line(text)


class Summary(NamedTuple):
    text: str
    at: int  # when it was stored (Unix seconds)


def summaries(con: sqlite3.Connection, email: str, slugs: list[str], shared: set[str] = frozenset()) -> dict[str, Summary]:
    """The newest non-empty summary per app and when it was stored, from the document store or the data API. Apps in `shared` have
    shared data (app/shared.py): their line is the shared document's, the same for everyone."""
    if not slugs:
        return {}
    email = email.lower()
    own = [s for s in slugs if s not in shared]
    common = [s for s in slugs if s in shared]
    own_marks, common_marks = ",".join("?" * len(own)), ",".join("?" * len(common))
    rows = con.execute(
        f"""SELECT slug, data AS raw, updated_at AS at FROM docs
              WHERE collection=? AND doc_id=?
                AND ((owner=? AND slug IN ({own_marks})) OR (owner=? AND slug IN ({common_marks})))
            UNION ALL
            SELECT app AS slug, value AS raw, updated AS at FROM app_data
              WHERE email=? AND key=? AND app IN ({own_marks})
            ORDER BY at""",
        (*SUMMARY_DOC, email, *own, SHARED, *common, email, SUMMARY_KEY, *own),
    ).fetchall()
    out: dict[str, Summary] = {}
    for r in rows:  # oldest first, so the newest valid one is left standing
        text = _text(r["raw"])
        if text:
            out[r["slug"]] = Summary(text, int(r["at"]))
    return out


# ---------------------------------------------------------------- sections
def build_sections(apps: list[dict], stats: dict, pins: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split the visible apps into "Favoritter", "Mest brukt" and the rest; marks each with pinned/new.

    Favoritter: every pinned app, in pin order. Mest brukt: the four most opened in the last 30 days
    (ties: latest open) that are not favourites. Each app appears once.
    """
    by_slug = {a["slug"]: a for a in apps}
    for a in apps:
        seen = stats.get(a["slug"])
        a["pinned"] = a["slug"] in pins
        a["new"] = bool(seen) and seen["last"] < int(a["updated"])  # visits are whole seconds, mtimes are not
    favs = [by_slug[p] for p in pins if p in by_slug]
    top = sorted(
        (a for a in apps if not a["pinned"] and stats.get(a["slug"], {}).get("count")),
        key=lambda a: (-stats[a["slug"]]["count"], -stats[a["slug"]]["last"]),
    )[:MOST_USED_MAX]
    shown = {a["slug"] for a in favs + top}
    return favs, top, [a for a in apps if a["slug"] not in shown]
