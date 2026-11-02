"""Front page data, per logged-in user: which apps they have chosen for it, which apps they have seen in the
«Arrange apps» list, which apps they open, what they pin, the groups they sort apps into, how they view the list, and the
one-line summary each app can leave for its card.

Everything takes an open connection from main.db() (rows as sqlite3.Row) and an e-mail; nothing here
is shared between users, except the summary line of apps with shared data (app/shared.py).
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app import i18n
from app.shared import SHARED

DAY = 86400
MOST_USED_DAYS = 30    # the window of visit_stats (opens in the last 30 days)
KEEP_DAYS = 90         # visits older than this are deleted
REVISIT_GAP = 600      # opening the same app again within 10 minutes (reloads) is not a new visit
STATS_DAYS = 7         # the admin statistics cover the last week
SUMMARY_MAX = 140
GROUP_NAME_MAX = 40    # characters in a group name, after trimming
GROUPS_MAX = 30        # groups per user
VIEWS = ("icons", "cards")
SECTIONS = ("fav", "rest")    # the sections of the front page whose open/closed state is stored per user (groups keep theirs)
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


def get_section_open(con: sqlite3.Connection, email: str) -> dict[str, bool]:
    """Whether Favourites ("fav") and Other ("rest") are open lists (True) or a grid of icons (False). What the user last
    chose (prefs keys fav_open and rest_open); until then what the old view setting made of the page: open for
    "cards", closed otherwise. Reading stores nothing, so an upgrade changes no value."""
    fallback = get_prefs(con, email)["view"] == "cards"
    out = {}
    for section in SECTIONS:
        try:
            stored = _get(con, email, f"{section}_open", None)
        except ValueError:  # the stored text is not JSON
            stored = None
        out[section] = stored if isinstance(stored, bool) else fallback
    return out


def set_section_open(con: sqlite3.Connection, email: str, section: str, open: bool) -> None:
    if section not in SECTIONS:
        raise ValueError(i18n.t("err.unknown_section", section=section))
    _put(con, email, f"{section}_open", bool(open))


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
    """An app got a new address: it stays chosen, pinned, seen and in its group for everyone."""
    for row in con.execute("SELECT email, key, value FROM prefs WHERE key IN ('apps', 'seen', 'pins')").fetchall():
        value = json.loads(row["value"])
        if isinstance(value, list) and old in value:
            _put(con, row["email"], row["key"], [new if s == old else s for s in value if s != new])
    for row in con.execute("SELECT email FROM prefs WHERE key='groups'").fetchall():
        groups = get_groups(con, row["email"])
        if any(old in g["slugs"] for g in groups):
            for g in groups:
                g["slugs"] = [new if s == old else s for s in g["slugs"] if s != new]
            _put(con, row["email"], "groups", groups)


# ---------------------------------------------------------------- groups
# Stored whole under the prefs key "groups": [{"id", "name", "slugs", "open"}], in the order shown. Every change
# re-reads and cleans the stored list first, so an order or move saved from a stale page only touches what is
# still there: apps that moved to another group stay put, and a deleted group does not come back.
def get_groups(con: sqlite3.Connection, email: str) -> list[dict]:
    """The user's groups, each {"id", "name", "slugs", "open"}. Entries that are not well-formed and repeated ids
    are dropped; an app stays only in the first group that has it."""
    try:
        stored = _get(con, email, "groups", [])
    except ValueError:  # the stored text is not JSON
        return []
    groups: list[dict] = []
    ids: set[str] = set()
    taken: set[str] = set()
    for g in stored if isinstance(stored, list) else []:
        if not isinstance(g, dict) or not isinstance(g.get("id"), str) or not g["id"] or g["id"] in ids:
            continue
        if not isinstance(g.get("name"), str) or not g["name"].strip():
            continue
        ids.add(g["id"])
        slugs = [s for s in dict.fromkeys(_slugs(g.get("slugs"))) if s not in taken]
        taken.update(slugs)
        groups.append({"id": g["id"], "name": g["name"].strip(), "slugs": slugs,
                       "open": g["open"] if isinstance(g.get("open"), bool) else True})
    return groups


def _find(groups: list[dict], gid: str) -> dict:
    for g in groups:
        if g["id"] == gid:
            return g
    raise KeyError(gid)


def _group_name(name: object, others: list[dict]) -> str:
    """`name` trimmed; ValueError unless it is 1-40 characters and no other group has it (ignoring case)."""
    clean = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(clean) <= GROUP_NAME_MAX:
        raise ValueError(i18n.t("err.group_name"))
    if any(g["name"].casefold() == clean.casefold() for g in others):
        raise ValueError(i18n.t("err.group_taken", name=clean))
    return clean


def _take_out(groups: list[dict], slug: str) -> None:
    for g in groups:
        g["slugs"] = [s for s in g["slugs"] if s != slug]


def create_group(con: sqlite3.Connection, email: str, name: str, slug: str | None = None) -> dict:
    """A new open group last in the list; with `slug`, that app moves into it."""
    groups = get_groups(con, email)
    clean = _group_name(name, groups)
    if len(groups) >= GROUPS_MAX:
        raise ValueError(i18n.t("err.group_max"))
    group = {"id": secrets.token_hex(4), "name": clean, "slugs": [], "open": True}
    while any(g["id"] == group["id"] for g in groups):  # 32 bits: a clash is unlikely, but cheap to rule out
        group["id"] = secrets.token_hex(4)
    if slug is not None:
        _take_out(groups, slug)
        group["slugs"].append(slug)
    groups.append(group)
    _put(con, email, "groups", groups)
    return group


def rename_group(con: sqlite3.Connection, email: str, gid: str, name: str) -> dict:
    groups = get_groups(con, email)
    group = _find(groups, gid)
    group["name"] = _group_name(name, [g for g in groups if g is not group])
    _put(con, email, "groups", groups)
    return group


def delete_group(con: sqlite3.Connection, email: str, gid: str) -> None:
    """Its apps have no group afterwards."""
    groups = get_groups(con, email)
    _find(groups, gid)
    _put(con, email, "groups", [g for g in groups if g["id"] != gid])


def set_app_group(con: sqlite3.Connection, email: str, slug: str, gid: str | None) -> None:
    """Take the app out of any group; unless `gid` is None, put it last in that group."""
    groups = get_groups(con, email)
    target = _find(groups, gid) if gid is not None else None
    _take_out(groups, slug)
    if target is not None:
        target["slugs"].append(slug)
    _put(con, email, "groups", groups)


def _merge(old: list[str], order: list[str]) -> list[str]:
    """`old` reordered by `order`: the items of `order` that are in `old` (no duplicates, anything else ignored), in
    that order, and each item `order` left out right after the one it followed in `old` (the nearest one `order`
    has), or first when none came before it. The page sends only what it shows (no pinned apps, no empty groups), and
    a drop there must not move what it doesn't show to the end."""
    shown = [s for s in dict.fromkeys(order) if s in old]
    after: dict[str | None, list[str]] = {}
    anchor = None
    for s in old:
        if s in shown:
            anchor = s
        else:
            after.setdefault(anchor, []).append(s)
    out = list(after.get(None, []))
    for s in shown:
        out += [s, *after.get(s, [])]
    return out


def set_group_apps(con: sqlite3.Connection, email: str, gid: str, order: list[str]) -> list[str]:
    """Reorder one group (_merge): slugs not in this group are ignored, even if the page still thinks they are."""
    groups = get_groups(con, email)
    group = _find(groups, gid)
    group["slugs"] = _merge(group["slugs"], order)
    _put(con, email, "groups", groups)
    return group["slugs"]


def set_group_order(con: sqlite3.Connection, email: str, order: list[str]) -> list[str]:
    """Reorder the groups by id (_merge): ids that are gone are ignored, none is brought back."""
    groups = get_groups(con, email)
    by_id = {g["id"]: g for g in groups}
    ids = _merge([g["id"] for g in groups], order)
    _put(con, email, "groups", [by_id[i] for i in ids])
    return ids


def set_group_open(con: sqlite3.Connection, email: str, gid: str, open: bool) -> None:
    groups = get_groups(con, email)
    _find(groups, gid)["open"] = open
    _put(con, email, "groups", groups)


def picker(
    apps: list[dict], chosen: list[str], seen: list[str] | None, groups: list[dict]
) -> list[tuple[dict | None, list[dict]]]:
    """The «Arrange apps» list: (group, its apps) for each group in order, empty ones too, holding the apps in `apps`
    in the group's order; then (None, the apps in no group) in the order given (list_artifacts sorts by title). Every
    app is listed once, pinned or not. Marks each app added/unseen and its place in `apps` (sort, for the page).

    Unseen = came after the user last opened the list. Before the first opening nothing is unseen, and an
    app on the front page always counts as seen."""
    by_slug = {a["slug"]: a for a in apps}
    for i, a in enumerate(apps):
        a["added"] = a["slug"] in chosen
        a["unseen"] = seen is not None and not a["added"] and a["slug"] not in seen
        a["sort"] = i
    out: list[tuple[dict | None, list[dict]]] = []
    listed: set[str] = set()
    for g in groups:
        members = [by_slug[s] for s in g["slugs"] if s in by_slug and s not in listed]
        listed.update(a["slug"] for a in members)
        out.append((g, members))
    out.append((None, [a for a in apps if a["slug"] not in listed]))
    return out


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
def build_sections(
    apps: list[dict], stats: dict, pins: list[str], groups: list[dict]
) -> tuple[list[dict], list[tuple[dict, list[dict]]], list[dict]]:
    """Split the visible apps into "Favoritter", the user's groups and the rest; marks each with pinned/new.

    Favoritter: every pinned app, in pin order. Then (group, apps) for each group in order, holding its
    unpinned apps that are on the page, in the group's order; a group with none is left out. Then the rest,
    in the order given. Each app appears once; slugs that are not in `apps` (deleted, no longer visible) are skipped.
    """
    by_slug = {a["slug"]: a for a in apps}
    for a in apps:
        seen = stats.get(a["slug"])
        a["pinned"] = a["slug"] in pins
        a["new"] = bool(seen) and seen["last"] < int(a["updated"])  # visits are whole seconds, mtimes are not
    favs = [by_slug[p] for p in pins if p in by_slug]
    shown = {a["slug"] for a in favs}
    grouped: list[tuple[dict, list[dict]]] = []
    for g in groups:
        members = [by_slug[s] for s in g["slugs"] if s in by_slug and s not in shown]
        shown.update(a["slug"] for a in members)
        if members:
            grouped.append((g, members))
    return favs, grouped, [a for a in apps if a["slug"] not in shown]
