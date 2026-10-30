"""App code lock: a four-digit code per user, the apps that user has locked, and the attempt limit.

The code is stored as a scrypt hash (app/passwd.py) in `app_codes`; the chosen apps are rows in `app_locks`.
Five wrong codes in a row block the user for 15 minutes; the count and the block live in the db, so they
survive a restart and are shared by every worker. The code is never logged.

    python -m app.applock reset <email>   # prints a one-time code; the user must pick a new one
    python -m app.applock list
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app import i18n, passwd
from app.access import norm

MAX_FAILS = 5
BLOCK_SECONDS = 15 * 60
UNLOCK_TTL = 600  # seconds an unlock lasts


# ---------------------------------------------------------------- tables
def create_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS app_codes(
             email         TEXT PRIMARY KEY,
             hash          TEXT NOT NULL,
             must_change   INTEGER NOT NULL DEFAULT 0,
             updated_at    INTEGER NOT NULL,
             fails         INTEGER NOT NULL DEFAULT 0,
             blocked_until INTEGER NOT NULL DEFAULT 0)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS app_locks(
             email TEXT NOT NULL,
             slug  TEXT NOT NULL,
             PRIMARY KEY (email, slug))"""
    )


def valid_code(code: object) -> bool:
    # [0-9], not \d: \d accepts other scripts' digits, and fullmatch refuses a trailing newline
    return isinstance(code, str) and re.fullmatch(r"[0-9]{4}", code) is not None


def get(con: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT email, hash, must_change, updated_at, fails, blocked_until FROM app_codes WHERE email=?",
        (norm(email),),
    ).fetchone()


def set_code(con: sqlite3.Connection, email: str, code: str, *, must_change: bool = False, now: int | None = None) -> int:
    at = int(now if now is not None else time.time())
    if now is None:
        # updated_at invalidates pending unlocks; a change within the same second must still move it
        old = get(con, email)
        if old is not None and at <= old["updated_at"]:
            at = old["updated_at"] + 1
    # REPLACE puts fails and blocked_until back to 0
    con.execute(
        "INSERT OR REPLACE INTO app_codes(email, hash, must_change, updated_at) VALUES(?,?,?,?)",
        (norm(email), passwd.hash_password(code), int(must_change), at),
    )
    return at


def reset(con: sqlite3.Connection, email: str) -> str | None:
    """A new one-time code the user must replace, or None (and no change) if the user has no code."""
    if get(con, email) is None:
        return None
    code = f"{secrets.randbelow(10_000):04d}"
    set_code(con, email, code, must_change=True)
    return code


# ---------------------------------------------------------------- attempt limit
@dataclass(frozen=True)
class Check:
    ok: bool
    wait: int = 0  # seconds of block left
    must_change: bool = False


def _left(row: sqlite3.Row | None, now: int) -> int:
    return max(0, row["blocked_until"] - now) if row is not None else 0


def check(connect: Callable[[], sqlite3.Connection], email: str, code: object, *, now: int | None = None) -> Check:
    """Test a code against the user's. Every try is counted before scrypt runs, so a burst of parallel tries
    cannot pass the limit; a blocked user costs no scrypt at all."""
    at = int(now if now is not None else time.time())
    if not valid_code(code):
        with connect() as con:
            return Check(False, wait=_left(get(con, email), at))
    with connect() as con:
        counted = con.execute(
            """UPDATE app_codes SET
                 fails = CASE WHEN blocked_until > 0 THEN 1 ELSE fails + 1 END,
                 blocked_until = CASE WHEN blocked_until = 0 AND fails + 1 >= :max THEN :until ELSE 0 END
               WHERE email = :email AND blocked_until <= :now""",
            {"max": MAX_FAILS, "until": at + BLOCK_SECONDS, "email": norm(email), "now": at},
        )
        row = get(con, email)
    if counted.rowcount == 0:  # no code, or blocked
        return Check(False, wait=_left(row, at))
    # scrypt runs outside any transaction, so it never holds the db lock
    if passwd.verify_password(code, row["hash"]):
        with connect() as con:
            con.execute("UPDATE app_codes SET fails=0, blocked_until=0 WHERE email=?", (norm(email),))
        return Check(True, must_change=bool(row["must_change"]))
    with connect() as con:
        return Check(False, wait=_left(get(con, email), at))


# ---------------------------------------------------------------- locked apps
def is_locked(con: sqlite3.Connection, email: str, slug: str) -> bool:
    return con.execute("SELECT 1 FROM app_locks WHERE email=? AND slug=?", (norm(email), slug)).fetchone() is not None


def locked_slugs(con: sqlite3.Connection, email: str) -> set[str]:
    return {r[0] for r in con.execute("SELECT slug FROM app_locks WHERE email=?", (norm(email),))}


def set_locked(con: sqlite3.Connection, email: str, slug: str, on: bool) -> None:
    if on:
        con.execute("INSERT OR IGNORE INTO app_locks(email, slug) VALUES(?,?)", (norm(email), slug))
    else:
        con.execute("DELETE FROM app_locks WHERE email=? AND slug=?", (norm(email), slug))


def rename(con: sqlite3.Connection, old: str, new: str) -> None:
    con.execute("UPDATE OR REPLACE app_locks SET slug=? WHERE slug=?", (new, old))


def list_all(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT c.email, c.must_change, c.updated_at,
                  (SELECT COUNT(*) FROM app_locks l WHERE l.email = c.email) AS apps
           FROM app_codes c ORDER BY c.email"""
    ).fetchall()


def emails(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT email FROM app_codes")}


# ---------------------------------------------------------------- CLI
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(Path(os.environ.get("DB_PATH", "/data/hub.db")))
    con.row_factory = sqlite3.Row
    create_tables(con)
    return con


def _cmd_reset(email: str) -> int:
    with _connect() as con:
        code = reset(con, email)
    if code is None:
        print(i18n.t("cli.lock_no_code", email=norm(email)), file=sys.stderr)
        return 1
    print(i18n.t("cli.lock_reset", email=norm(email), code=code))
    return 0


def _cmd_list() -> int:
    with _connect() as con:
        for row in list_all(con):
            print(f"{row['email']}  {row['apps']}  {i18n.t('cli.must_change') if row['must_change'] else i18n.t('cli.is_set')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.applock", description="Manage hub app codes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset", help="give a user a one-time code")
    r.add_argument("email")
    sub.add_parser("list", help="list users with a code and how many apps they have locked")
    args = ap.parse_args(argv)
    return _cmd_reset(args.email) if args.cmd == "reset" else _cmd_list()


if __name__ == "__main__":
    sys.exit(main())
