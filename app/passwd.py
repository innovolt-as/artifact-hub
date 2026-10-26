"""Password login: scrypt hashes in the db table `passwords`, plus a CLI for the server owner.

Hash format: "scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>". The parameters are read from the string
when verifying, so they can be raised later without invalidating old hashes.

    python -m app.passwd set <email> [--temporary]   # prompts twice; --temporary forces a change at next login
    python -m app.passwd list
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app import i18n
from app.access import norm

N, R, P, DKLEN = 2**14, 8, 1, 32
MIN_LENGTH = 10


# Each scrypt run needs ~16 MiB (128 * n * r); cap concurrent runs so a burst of logins can't exhaust memory.
_scrypt_slots = threading.BoundedSemaphore(4)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    # maxmem: n=2**14, r=8 needs 16 MiB, which is under OpenSSL's default; the 128 MiB override is headroom
    # for stored hashes with higher parameters.
    with _scrypt_slots:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=128 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, N, R, P, DKLEN)
    salt64 = base64.b64encode(salt).decode()
    digest64 = base64.b64encode(digest).decode()
    return f"scrypt${N}${R}${P}${salt64}${digest64}"


def verify_password(password: str, stored: str) -> bool:
    """True if `password` matches `stored`; False on any mismatch or malformed hash, never an exception."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        expected_bytes = base64.b64decode(expected, validate=True)
        digest = _scrypt(password, base64.b64decode(salt, validate=True), int(n), int(r), int(p), len(expected_bytes))
        return hmac.compare_digest(digest, expected_bytes)
    except Exception:
        return False


# A valid hash of a random password, so a missing row costs the same time as a wrong password
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- table
def ensure_table(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS passwords(
             email       TEXT PRIMARY KEY,
             hash        TEXT NOT NULL,
             must_change INTEGER NOT NULL DEFAULT 0,
             updated_at  INTEGER NOT NULL)"""
    )


def get(con: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT email, hash, must_change, updated_at FROM passwords WHERE email=?", (norm(email),)
    ).fetchone()


def set_password(con: sqlite3.Connection, email: str, password: str, *, must_change: bool, now: int | None = None) -> int:
    at = int(now if now is not None else time.time())
    if now is None:
        # updated_at invalidates pending cookies; a reset within the same second must still change it
        old = get(con, email)
        if old is not None and at <= old["updated_at"]:
            at = old["updated_at"] + 1
    con.execute(
        "INSERT OR REPLACE INTO passwords(email, hash, must_change, updated_at) VALUES(?,?,?,?)",
        (norm(email), hash_password(password), int(must_change), at),
    )
    return at


def delete(con: sqlite3.Connection, email: str) -> None:
    con.execute("DELETE FROM passwords WHERE email=?", (norm(email),))


def list_all(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT email, hash, must_change, updated_at FROM passwords ORDER BY email").fetchall()


# ---------------------------------------------------------------- CLI
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(Path(os.environ.get("DB_PATH", "/data/hub.db")))
    con.row_factory = sqlite3.Row
    ensure_table(con)
    return con


def _read_password(prompt: str) -> str:
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass(prompt)
    return sys.stdin.readline().rstrip("\r\n")


def _cmd_set(email: str, temporary: bool) -> int:
    first = _read_password(i18n.t("cli.password"))
    second = _read_password(i18n.t("cli.repeat"))
    if first != second:
        print(i18n.t("cli.mismatch"), file=sys.stderr)
        return 2
    if len(first) < MIN_LENGTH:
        print(i18n.t("cli.short", min=MIN_LENGTH), file=sys.stderr)
        return 2
    with _connect() as con:
        set_password(con, email, first, must_change=temporary)
    print(i18n.t("cli.set_temp" if temporary else "cli.set", email=norm(email)))
    from app import main  # lazily: main imports this module
    if not main.email_allowed(norm(email)):
        print(i18n.t("cli.not_allowed", email=norm(email)), file=sys.stderr)
    return 0


def _cmd_list() -> int:
    with _connect() as con:
        for row in list_all(con):
            when = datetime.fromtimestamp(row["updated_at"], timezone.utc).isoformat()
            print(f"{row['email']}  {i18n.t('cli.must_change') if row['must_change'] else i18n.t('cli.is_set')}  {when}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.passwd", description="Manage hub passwords")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="set or replace a user's password")
    s.add_argument("email")
    s.add_argument("--temporary", action="store_true", help="user must change it at first login")
    sub.add_parser("list", help="list users with a password")
    args = ap.parse_args(argv)
    return _cmd_set(args.email, args.temporary) if args.cmd == "set" else _cmd_list()


if __name__ == "__main__":
    sys.exit(main())
