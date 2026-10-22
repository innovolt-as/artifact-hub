"""Front page data, per logged-in user: which apps they open, what they pin, how they view the list,
and the one-line summary each app can leave for its card.

Everything takes an open connection from main.db() (rows as sqlite3.Row) and an e-mail; nothing here
is shared between users.
"""
from __future__ import annotations

import json
import sqlite3
import time

DAY = 86400
MOST_USED_DAYS = 30    # what counts towards "Mest brukt"
KEEP_DAYS = 90         # visits older than this are deleted
REVISIT_GAP = 600      # opening the same app again within 10 minutes (reloads) is not a new visit
MOST_USED_MAX = 4
SUMMARY_MAX = 140
VIEWS = ("icons", "cards")
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


# ---------------------------------------------------------------- prefs
def _get(con: sqlite3.Connection, email: str, key: str, default):
    row = con.execute("SELECT value FROM prefs WHERE email=? AND key=?", (email.lower(), key)).fetchone()
    return json.loads(row["value"]) if row else default


def _put(con: sqlite3.Connection, email: str, key: str, value) -> None:
    con.execute(
        "INSERT INTO prefs(email, key, value) VALUES(?,?,?) ON CONFLICT(email, key) DO UPDATE SET value=excluded.value",
        (email.lower(), key, json.dumps(value)),
    )


def get_prefs(con: sqlite3.Connection, email: str) -> dict:
    view = _get(con, email, "view", "icons")
    pins = _get(con, email, "pins", [])
    return {"view": view if view in VIEWS else "icons", "pins": [p for p in pins if isinstance(p, str)]}


def set_view(con: sqlite3.Connection, email: str, view: str) -> None:
    if view not in VIEWS:
        raise ValueError(f"Ukjent visning: {view}")
    _put(con, email, "view", view)


def set_pin(con: sqlite3.Connection, email: str, slug: str, pinned: bool) -> list[str]:
    pins = [p for p in get_prefs(con, email)["pins"] if p != slug]
    if pinned:
        pins.append(slug)
    _put(con, email, "pins", pins)
    return pins


# ---------------------------------------------------------------- summaries
def _text(raw: str) -> str | None:
    try:
        text = json.loads(raw).get("text")
    except (ValueError, AttributeError):
        return None
    return text.strip()[:SUMMARY_MAX] if isinstance(text, str) and text.strip() else None


def summaries(con: sqlite3.Connection, email: str, slugs: list[str]) -> dict[str, str]:
    """The newest non-empty summary per app, from the document store or the data API."""
    if not slugs:
        return {}
    email = email.lower()
    marks = ",".join("?" * len(slugs))
    rows = con.execute(
        f"""SELECT slug, data AS raw, updated_at AS at FROM docs
              WHERE owner=? AND collection=? AND doc_id=? AND slug IN ({marks})
            UNION ALL
            SELECT app AS slug, value AS raw, updated AS at FROM app_data
              WHERE email=? AND key=? AND app IN ({marks})
            ORDER BY at""",
        (email, *SUMMARY_DOC, *slugs, email, SUMMARY_KEY, *slugs),
    ).fetchall()
    out: dict[str, str] = {}
    for r in rows:  # oldest first, so the newest valid one is left standing
        text = _text(r["raw"])
        if text:
            out[r["slug"]] = text
    return out


# ---------------------------------------------------------------- sections
def build_sections(apps: list[dict], stats: dict, pins: list[str]) -> tuple[list[dict], list[dict]]:
    """Split the visible apps into "Mest brukt" and the rest; marks each with pinned/new.

    Pinned apps come first in pin order, then the most opened in the last 30 days (ties: latest open)
    up to four in all. More than four pins: all of them. Each app appears once.
    """
    by_slug = {a["slug"]: a for a in apps}
    for a in apps:
        seen = stats.get(a["slug"])
        a["pinned"] = a["slug"] in pins
        a["new"] = bool(seen) and seen["last"] < int(a["updated"])  # visits are whole seconds, mtimes are not
    top = [by_slug[p] for p in pins if p in by_slug]
    used = sorted(
        (a for a in apps if not a["pinned"] and stats.get(a["slug"], {}).get("count")),
        key=lambda a: (-stats[a["slug"]]["count"], -stats[a["slug"]]["last"]),
    )
    top += used[: max(0, MOST_USED_MAX - len(top))]
    in_top = {a["slug"] for a in top}
    return top, [a for a in apps if a["slug"] not in in_top]
