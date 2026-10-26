"""
Artifact Hub — host Claude artifacts behind a magic-link login.

Layout of the data dir (ARTIFACTS_DIR, default /data/artifacts):
    my-chart.html                  -> served at /a/my-chart/
    my-app/index.html (+ assets)   -> served at /a/my-app/
    my-chart.meta.json             -> optional: {"title": "...", "description": "...", "admin_only": true}
    my-app/meta.json               -> same, for folder artifacts
    recall.link.json               -> external link card: {"title": "...", "url": "...", "admin_only": true}

Who sees an app (app/access.py): "admin_only": true = only admins; "access": "people" with "people": [e-mails]
= those people; neither = everyone who can log in.

Artifacts can keep per-user data through /api/me and /api/data/{app}/... (see "per-user app data" below).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2.utils import htmlsafe_json_dumps

from app import access, banner, home, i18n, loginmail, mail, passwd, versions

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------- config
BASE_DIR = Path(__file__).parent
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/data/artifacts"))
DB_PATH = Path(os.environ.get("DB_PATH", "/data/hub.db"))
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
SITE_NAME = os.environ.get("SITE_NAME", "Artifact Hub")
# Optional branding: files with these names in BRANDING_DIR replace the defaults in app/static/
BRANDING_DIR = Path(os.environ.get("BRANDING_DIR") or DB_PATH.parent / "branding")
BRANDING_FILES = ("logo.svg", "favicon-32.png", "apple-touch-icon.png")

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
ALLOWED_EMAILS = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
ALLOWED_DOMAINS = {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()}
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")  # for scripts/push.sh
LOGIN_MODE = os.environ.get("LOGIN_MODE") or "magic-link"  # 'magic-link' (default) or 'password'
if LOGIN_MODE not in ("magic-link", "password"):
    raise SystemExit(f"LOGIN_MODE must be 'magic-link' or 'password', got '{LOGIN_MODE}'")


def password_mode() -> bool:
    return LOGIN_MODE == "password"


MAGIC_TTL = 15 * 60               # seconds a magic link is valid
SESSION_TTL = 30 * 24 * 3600      # seconds a session cookie lives
COOKIE = "hub_session"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OPEN_SIGNUP = "*" in ALLOWED_DOMAINS  # ALLOWED_DOMAINS=* lets anyone with an e-mail log in

# Rate limits for sending magic links (protects the SMTP sender from being used for spam)
MAX_LINKS_PER_EMAIL = 3           # unexpired links per address (i.e. per MAGIC_TTL)
MAX_LINKS_PER_IP = 10             # per hour
_ip_sends: dict[str, list[float]] = {}
PENDING_TTL = 30 * 60             # seconds a "must change password" cookie lives
MAX_PW_FAILS_PER_EMAIL = 10       # failed password logins per address per 15 minutes
MAX_PW_FAILS_PER_IP = 30          # failed password logins per IP per hour
PW_FAIL_WINDOW_EMAIL = 15 * 60
PW_FAIL_WINDOW_IP = 3600
_pw_lock = threading.Lock()  # sync routes run in a thread pool; guards _pw_fails
_pw_fails: dict[str, list[float]] = {}   # keys "e:<email>" and "ip:<ip>"

ICONS_DIR = ARTIFACTS_DIR / ".icons"  # <slug>.<ext>, uploaded via the admin page
ICON_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}
MAX_ICON_BYTES = 2 * 1024 * 1024
META_KEYS = ("title", "description", "emoji", "admin_only", "access", "people", "banner")  # what survives a re-upload

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None)
def static_file(name: str) -> Path:
    """The file served for /static/<name>: the branded one if the operator provided it, else the default."""
    if name in BRANDING_FILES and (BRANDING_DIR / name).is_file():
        return BRANDING_DIR / name
    return BASE_DIR / "static" / name


class BrandedStatic(StaticFiles):
    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        if path in BRANDING_FILES:
            f = static_file(path)
            return str(f), os.stat(f)
        return super().lookup_path(path)


app.mount("/static", BrandedStatic(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["pw_mode"] = lambda: password_mode()
templates.env.globals.update(t=i18n.t, t_html=i18n.t_html, tn=i18n.tn, raw=i18n.raw, lang=lambda: i18n.LANG)
signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")


# ---------------------------------------------------------------- db
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute(
        """CREATE TABLE IF NOT EXISTS magic_tokens(
             token_hash TEXT PRIMARY KEY,
             email      TEXT NOT NULL,
             expires_at INTEGER NOT NULL,
             used       INTEGER NOT NULL DEFAULT 0)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS logins(
             email TEXT NOT NULL, at INTEGER NOT NULL)"""
    )
    # Document store behind window.claude.use("db") (static/hub.js): private per artifact and per user
    con.execute(
        """CREATE TABLE IF NOT EXISTS docs(
             slug       TEXT NOT NULL,
             owner      TEXT NOT NULL,
             collection TEXT NOT NULL,
             doc_id     TEXT NOT NULL,
             data       TEXT NOT NULL,
             updated_at INTEGER NOT NULL,
             PRIMARY KEY (slug, owner, collection, doc_id))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS app_data(
             email   TEXT NOT NULL,
             app     TEXT NOT NULL,
             key     TEXT NOT NULL,
             value   TEXT NOT NULL,
             updated INTEGER NOT NULL,
             PRIMARY KEY (email, app, key))"""
    )
    # OAuth for the Claude connector (app/oauth.py); codes and tokens are stored as SHA-256 hashes
    con.execute("CREATE TABLE IF NOT EXISTS oauth_clients(client_id TEXT PRIMARY KEY, info TEXT NOT NULL)")
    con.execute(
        """CREATE TABLE IF NOT EXISTS oauth_requests(
             id         TEXT PRIMARY KEY,
             client_id  TEXT NOT NULL,
             params     TEXT NOT NULL,
             expires_at INTEGER NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS oauth_codes(
             code_hash  TEXT PRIMARY KEY,
             client_id  TEXT NOT NULL,
             email      TEXT NOT NULL,
             params     TEXT NOT NULL,
             expires_at REAL NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS oauth_tokens(
             token_hash TEXT PRIMARY KEY,
             kind       TEXT NOT NULL,          -- 'access' | 'refresh'
             client_id  TEXT NOT NULL,
             email      TEXT NOT NULL,
             scopes     TEXT NOT NULL,
             resource   TEXT,
             expires_at INTEGER NOT NULL)"""
    )
    # Front page per user: app opens, pins and view mode (app/home.py)
    home.create_tables(con)
    # People the admin has invited; they may log in (app/access.py)
    access.create_tables(con)
    # Password hashes for LOGIN_MODE=password (app/passwd.py)
    passwd.ensure_table(con)
    if password_mode() and not any(passwd.get(con, e) for e in ADMIN_EMAILS):
        log.warning("LOGIN_MODE=password but no admin has a password yet — run: "
                    "docker compose exec hub python -m app.passwd set <admin e-mail>")


# ---------------------------------------------------------------- auth helpers
def allowed_by_config(email: str) -> bool:
    """Let in by the server config (ADMIN_EMAILS, ALLOWED_EMAILS, ALLOWED_DOMAINS), not by an invitation."""
    email = email.lower()
    if email in ADMIN_EMAILS or email in ALLOWED_EMAILS:
        return True
    if OPEN_SIGNUP:
        return bool(EMAIL_RE.match(email))
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return domain in ALLOWED_DOMAINS


def email_allowed(email: str) -> bool:
    if allowed_by_config(email):
        return True
    with db() as con:
        return access.is_invited(con, email)


def is_admin(email: str | None) -> bool:
    return bool(email) and email.lower() in ADMIN_EMAILS


def can_see(meta: dict, user: str | None) -> bool:
    """Whether `user` may see the app with this meta (app/access.py)."""
    return access.can_see(meta, user, is_admin(user))


def current_user(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = signer.loads(raw, max_age=SESSION_TTL)
        if "pw_change" in data:  # pending cookie: not logged in yet
            return None
        return data["email"]
    except (BadSignature, KeyError):
        return None


def pending_password_user(request: Request) -> tuple[str, int] | None:
    """(email, pw_at) from a pending cookie (temporary password, change required), else None."""
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = signer.loads(raw, max_age=PENDING_TTL)
        if not data.get("pw_change"):
            return None
        return data["email"], int(data["pw_at"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None


def _set_cookie(resp, payload: dict, max_age: int) -> None:
    resp.set_cookie(
        COOKIE,
        signer.dumps(payload),
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=BASE_URL.startswith("https://"),
    )


def set_session(resp, email: str) -> None:
    _set_cookie(resp, {"email": email}, SESSION_TTL)


def set_pending(resp, email: str, pw_at: int) -> None:
    _set_cookie(resp, {"email": email, "pw_change": True, "pw_at": pw_at}, PENDING_TTL)


def _pw_window(key: str) -> int:
    return PW_FAIL_WINDOW_EMAIL if key.startswith("e:") else PW_FAIL_WINDOW_IP


def _pw_prune(now: float) -> None:
    """Drop expired entries from every key, and keys that end up empty."""
    for key in list(_pw_fails):
        recent = [t for t in _pw_fails[key] if now - t < _pw_window(key)]
        if recent:
            _pw_fails[key] = recent
        else:
            del _pw_fails[key]


def pw_rate_limited(email: str, ip: str, since: int = 0) -> bool:
    """`since` is the password's updated_at: e-mail failures from before a (re)set don't count,
    so a reset (CLI or admin) lifts the e-mail lockout. The IP limit is unaffected."""
    with _pw_lock:
        now = time.time()
        _pw_prune(now)
        # updated_at has whole-second resolution; a failure in the same second as a reset still counts
        n_email = sum(1 for t in _pw_fails.get(f"e:{email}", []) if t >= since)
        return (n_email >= MAX_PW_FAILS_PER_EMAIL
                or len(_pw_fails.get(f"ip:{ip}", [])) >= MAX_PW_FAILS_PER_IP)


def pw_fail(email: str, ip: str) -> None:
    with _pw_lock:
        now = time.time()
        _pw_prune(now)
        if len(_pw_fails) > 10000:  # still too big after pruning: drop the oldest keys
            for k in sorted(_pw_fails, key=lambda k: _pw_fails[k][-1])[:5000]:
                del _pw_fails[k]
        for key in (f"e:{email}", f"ip:{ip}"):
            _pw_fails.setdefault(key, []).append(now)


def pw_clear(email: str) -> None:
    with _pw_lock:
        _pw_fails.pop(f"e:{email}", None)


def ip_rate_limited(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _ip_sends.get(ip, []) if now - t < 3600]
    if len(recent) >= MAX_LINKS_PER_IP:
        _ip_sends[ip] = recent
        return True
    _ip_sends[ip] = recent + [now]
    return False


def safe_next(url: str | None) -> str:
    """Only allow local paths as post-login targets (no open redirects)."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/"
    return url


def require_user(request: Request) -> str:
    user = current_user(request)
    if not user:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        loc = "/login" if target == "/" else f"/login?next={quote(target, safe='')}"
        raise HTTPException(status_code=302, headers={"Location": loc})
    return user


def require_admin(request: Request) -> str:
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail=i18n.t("err.admin_only"))
    return user


def send_magic_link(email: str, link: str) -> None:
    try:
        icon = static_file("apple-touch-icon.png").read_bytes()
    except OSError:
        icon = None
    m = loginmail.build(link, SITE_NAME, MAGIC_TTL // 60, icon)
    if not mail.send(email, m.subject, m.text, html=m.html, images=m.images, sender_name=SITE_NAME):
        log.warning("SMTP not configured — magic link for %s: %s", email, link)


# ---------------------------------------------------------------- artifact catalogue
def _read_meta(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        log.warning("Bad JSON in %s", path)
        return {}


def _title_from_html(path: Path, fallback: str) -> str:
    try:
        head = path.read_text("utf-8", errors="ignore")[:4000]
        m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip() or fallback
    except OSError:
        pass
    return fallback


def _meta_path(slug: str) -> Path | None:
    """Where an artifact's metadata lives (link cards keep it in the .link.json itself)."""
    if not SLUG_RE.match(slug):
        return None
    if (ARTIFACTS_DIR / f"{slug}.html").is_file():
        return ARTIFACTS_DIR / f"{slug}.meta.json"
    if (ARTIFACTS_DIR / slug / "index.html").is_file():
        return ARTIFACTS_DIR / slug / "meta.json"
    if (ARTIFACTS_DIR / f"{slug}.link.json").is_file():
        return ARTIFACTS_DIR / f"{slug}.link.json"
    return None


def _icon_file(slug: str) -> Path | None:
    for ext in ICON_TYPES:
        p = ICONS_DIR / f"{slug}{ext}"
        if p.is_file():
            return p
    return None


def _remove_icon(slug: str) -> None:
    for ext in ICON_TYPES:
        (ICONS_DIR / f"{slug}{ext}").unlink(missing_ok=True)


_NO_ORDER = str.maketrans({"æ": "z{", "ø": "z|", "å": "z}"})  # i18n-ok: æ ø å after z, in that order


def _sort_key(title: str) -> str:
    return title.casefold().translate(_NO_ORDER)


def list_artifacts(user: str) -> list[dict]:
    items: list[dict] = []
    admin = is_admin(user)
    for p in sorted(ARTIFACTS_DIR.iterdir()):
        name = p.name
        if name.startswith(".") or name.endswith(".meta.json"):
            continue
        if name.endswith(".link.json"):
            slug = name[: -len(".link.json")]
            meta = _read_meta(p)
            kind, url, mtime = "link", meta.get("url", "#"), p.stat().st_mtime
            fallback = slug
        elif p.is_file() and name.endswith(".html"):
            slug = name[: -len(".html")]
            meta = _read_meta(ARTIFACTS_DIR / f"{slug}.meta.json")
            kind, url, mtime = "page", f"/a/{slug}/", p.stat().st_mtime
            fallback = _title_from_html(p, slug)
        elif p.is_dir() and (p / "index.html").exists():
            slug = name
            meta = _read_meta(p / "meta.json")
            kind, url, mtime = "app", f"/a/{slug}/", (p / "index.html").stat().st_mtime
            fallback = _title_from_html(p / "index.html", slug)
        else:
            continue
        if not access.can_see(meta, user, admin):
            continue
        icon = _icon_file(slug)
        items.append(
            {
                "slug": slug,
                "kind": kind,
                "url": url,
                "open_url": f"/go/{slug}" if kind == "link" else url,  # /go logs the open, then redirects
                "title": meta.get("title") or fallback,
                "description": meta.get("description", ""),
                "admin_only": access.level(meta) == "admin",
                "access": access.level(meta),
                "access_label": access.label(meta),
                "access_text": access.describe(meta),
                "people": access.people(meta) if admin else [],
                "banner": meta.get("banner") is not False,  # the strip at the top of the app (banner.py)
                "updated": mtime,
                "emoji": meta.get("emoji", ""),
                "icon_url": f"/icon/{slug}?v={int(icon.stat().st_mtime)}" if icon else None,
                "hue": int(hashlib.md5(slug.encode()).hexdigest()[:4], 16) % 360,  # letter-fallback colour
            }
        )
    items.sort(key=lambda a: _sort_key(a["title"]))
    return items


def artifact_root(slug: str) -> tuple[Path, dict] | None:
    """Return (path, meta) for a slug, or None."""
    if not SLUG_RE.match(slug):
        return None
    f = ARTIFACTS_DIR / f"{slug}.html"
    if f.is_file():
        return f, _read_meta(ARTIFACTS_DIR / f"{slug}.meta.json")
    d = ARTIFACTS_DIR / slug
    if d.is_dir() and (d / "index.html").is_file():
        return d, _read_meta(d / "meta.json")
    return None


# ---------------------------------------------------------------- routes: auth
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    next = safe_next(next)
    if current_user(request):
        return RedirectResponse(next, status_code=302)
    return templates.TemplateResponse(request, "login.html", {
        "site": SITE_NAME, "sent": False, "next": next, "error": None,
        "mode": "password" if password_mode() else "magic-link"})


def login_password(request: Request, email: str, password: str, next: str):
    ip = request.client.host if request.client else "?"

    def fail():
        return templates.TemplateResponse(request, "login.html", {
            "site": SITE_NAME, "sent": False, "next": next, "error": i18n.t("login.error"), "mode": "password"})

    with db() as con:
        row = passwd.get(con, email)  # before the rate limit: a reset (new updated_at) lifts the e-mail lockout
    if len(password) > 1024 or pw_rate_limited(email, ip, row["updated_at"] if row else 0):
        if len(password) <= 1024:
            log.warning("Rate limited password login for %s from %s", email, ip)
        else:
            pw_fail(email, ip)
        return fail()
    # Always verify (against a dummy hash if no row) so timing doesn't reveal who has a password.
    ok = passwd.verify_password(password, row["hash"] if row else passwd.DUMMY_HASH)
    ok = ok and row is not None and email_allowed(email)
    if not ok:
        pw_fail(email, ip)
        log.info("Failed password login for %r from %s", email, ip)
        return fail()
    pw_clear(email)
    if row["must_change"]:
        loc = "/password" if next == "/" else f"/password?next={quote(next, safe='')}"
        resp = RedirectResponse(loc, status_code=302)
        set_pending(resp, email, row["updated_at"])
        return resp
    with db() as con:
        con.execute("INSERT INTO logins(email, at) VALUES(?,?)", (email, int(time.time())))
    resp = RedirectResponse(next, status_code=302)
    set_session(resp, email)
    return resp


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), next: str = Form("/"), password: str = Form("")):
    email = email.strip().lower()
    next = safe_next(next)
    if password_mode():
        return login_password(request, email, password, next)
    # Always show "sent" so we don't leak who is on the allowlist.
    ip = request.client.host if request.client else "?"
    if email_allowed(email):
        with db() as con:
            pending = con.execute(
                "SELECT COUNT(*) FROM magic_tokens WHERE email=? AND used=0 AND expires_at>?",
                (email, int(time.time())),
            ).fetchone()[0]
        if pending >= MAX_LINKS_PER_EMAIL or ip_rate_limited(ip):
            log.warning("Rate limited magic link for %s from %s", email, ip)
            return templates.TemplateResponse(request, "login.html", {"site": SITE_NAME, "sent": True, "email": email, "minutes": MAGIC_TTL // 60})
        token = secrets.token_urlsafe(32)
        with db() as con:
            con.execute(
                "INSERT INTO magic_tokens(token_hash,email,expires_at) VALUES(?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), email, int(time.time()) + MAGIC_TTL),
            )
        try:
            link = f"{BASE_URL}/auth?token={token}"
            if next != "/":
                link += f"&next={quote(next, safe='')}"
            send_magic_link(email, link)
        except Exception as e:  # noqa: BLE001
            log.exception("Could not send magic link: %s", e)
    else:
        log.info("Login attempt from non-allowed email %s", email)
    return templates.TemplateResponse(request, "login.html", {"site": SITE_NAME, "sent": True, "email": email, "minutes": MAGIC_TTL // 60})


@app.get("/auth")
def auth(token: str, next: str = "/"):
    if password_mode():
        raise HTTPException(status_code=404)
    h = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with db() as con:
        row = con.execute("SELECT email, expires_at, used FROM magic_tokens WHERE token_hash=?", (h,)).fetchone()
        if not row or row["used"] or row["expires_at"] < now:
            raise HTTPException(status_code=400, detail=i18n.t("auth.invalid"))
        con.execute("UPDATE magic_tokens SET used=1 WHERE token_hash=?", (h,))
        con.execute("DELETE FROM magic_tokens WHERE expires_at < ?", (now,))
        con.execute("INSERT INTO logins(email, at) VALUES(?,?)", (row["email"], now))
    resp = RedirectResponse(safe_next(next), status_code=302)
    set_session(resp, row["email"])
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


def _password_form(request, pending: bool, next: str, error: str | None = None, no_password: bool = False):
    return templates.TemplateResponse(request, "password.html", {
        "site": SITE_NAME, "pending": pending, "next": next, "error": error, "no_password": no_password,
        "user": None if pending else current_user(request)})


@app.get("/password", response_class=HTMLResponse)
def password_page(request: Request, next: str = "/"):
    if not password_mode():
        raise HTTPException(404)
    pending = pending_password_user(request)
    if not pending and not current_user(request):
        return RedirectResponse("/login", status_code=302)
    if not pending:
        with db() as con:
            if passwd.get(con, current_user(request)) is None:
                return _password_form(request, False, safe_next(next), no_password=True)
    return _password_form(request, bool(pending), safe_next(next))


@app.post("/password", response_class=HTMLResponse)
def password_submit(request: Request, new1: str = Form(""), new2: str = Form(""),
                    current: str = Form(""), next: str = Form("/")):
    if not password_mode():
        raise HTTPException(404)
    next = safe_next(next)
    ip = request.client.host if request.client else "?"
    pending = pending_password_user(request)
    if pending:
        email, pw_at = pending
        with db() as con:
            row = passwd.get(con, email)
        # A stale pending cookie (password reset again, person removed) must not work.
        if (not email_allowed(email) or row is None or row["must_change"] != 1
                or row["updated_at"] != pw_at):
            raise HTTPException(403, i18n.t("password.invalid"))
    else:
        email = current_user(request)
        if not email:
            return RedirectResponse("/login", status_code=302)
        with db() as con:
            row = passwd.get(con, email)
        if row is None:
            return _password_form(request, False, next, no_password=True)
        if pw_rate_limited(email, ip, row["updated_at"]):
            return _password_form(request, False, next, i18n.t("password.err.rate"))
        if not passwd.verify_password(current, row["hash"]):
            pw_fail(email, ip)
            return _password_form(request, False, next, i18n.t("password.err.wrong"))
    error = None
    if len(new1) < 10:
        error = i18n.t("password.err.short")
    elif len(new1) > 200:
        error = i18n.t("password.err.long")
    elif new1 != new2:
        error = i18n.t("password.err.mismatch")
    elif passwd.verify_password(new1, row["hash"]):
        error = i18n.t("password.err.same")
    if error:
        return _password_form(request, bool(pending), next, error)
    with db() as con:
        passwd.set_password(con, email, new1, must_change=False)
        if pending:
            con.execute("INSERT INTO logins(email, at) VALUES(?,?)", (email, int(time.time())))
    pw_clear(email)
    resp = RedirectResponse(next if pending else "/?pw=changed", status_code=302)
    set_session(resp, email)
    return resp


# ---------------------------------------------------------------- routes: gallery + serving
@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: str = Depends(require_user)):
    notice = i18n.t("home.pw_changed") if request.query_params.get("pw") == "changed" else None
    apps = list_artifacts(user)
    with db() as con:
        home.start(con, user, [a["slug"] for a in apps], admin=is_admin(user))
        prefs = home.get_prefs(con, user)
        mine = [a for a in apps if a["slug"] in prefs["apps"]]  # only the apps this user has chosen
        stats = home.visit_stats(con, user)
        summaries = home.summaries(con, user, [a["slug"] for a in mine]) if prefs["view"] == "cards" else {}
    favs, top, rest = home.build_sections(mine, stats, prefs["pins"])
    available = home.picker(apps, prefs["apps"], prefs["seen"])
    now = time.localtime()  # fallback only; the page rewrites the date and greeting with the viewer's clock
    return templates.TemplateResponse(
        request,
        "index.html",
        {"site": SITE_NAME, "user": user, "admin": is_admin(user), "notice": notice, "view": prefs["view"], "favs": favs, "top": top, "rest": rest,
         "available": available, "has_new": any(a["unseen"] for a in available), "summaries": summaries, "today": i18n.t("date.today", day=i18n.t_list("date.days")[now.tm_wday], date=now.tm_mday, month=i18n.t_list("date.months")[now.tm_mon - 1]),
         "js_strings": {**i18n.js("js.home."), "locale": i18n.t("locale")}},
    )


@app.get("/manifest.webmanifest")
def manifest():
    """Lets the hub be added to a phone's home screen and open without the browser bar."""
    return JSONResponse(
        {
            "name": SITE_NAME,
            "short_name": SITE_NAME,
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0b1a33",
            "theme_color": "#0b1a33",
            "icons": [
                {"src": "/static/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                {"src": "/static/logo.svg", "sizes": "any", "type": "image/svg+xml"},
            ],
        },
        media_type="application/manifest+json",
    )


@app.get("/a/{slug}")
def artifact_redirect(slug: str):
    return RedirectResponse(f"/a/{slug}/", status_code=301)


@app.get("/a/{slug}/{path:path}")
def serve_artifact(slug: str, path: str, request: Request, user: str = Depends(require_user)):
    found = artifact_root(slug)
    if not found:
        raise HTTPException(404)
    root, meta = found
    if not can_see(meta, user):
        raise HTTPException(404)
    if path in ("", "index.html"):
        _log_visit(user, slug)
    # only a page the browser opens gets the banner, not HTML an app fetches or shows in an iframe
    with_banner = request.headers.get("sec-fetch-dest", "document") == "document"
    if root.is_file():
        if path not in ("", "index.html"):
            raise HTTPException(404)
        return _html_with_shim(root, slug, user, with_banner=with_banner)
    target = (root / (path or "index.html")).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise HTTPException(404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file() or target.name == "meta.json":
        raise HTTPException(404)
    if target.suffix.lower() in (".html", ".htm"):
        return _html_with_shim(target, slug, user, with_banner=with_banner)
    return FileResponse(target)


# Apps are used on phones and must never scroll sideways. iOS zooms in on inputs under 16px and
# stays zoomed (which reads as sideways scroll), and a stray wide element widens the whole page.
# overflow-x: clip (unlike hidden) keeps position: sticky working.
NO_SIDEWAYS_CSS = (
    "<style>html,body{overflow-x: clip !important}"
    "@media (pointer:coarse){input,select,textarea{font-size: max(16px, 1em) !important}}</style>"
)


# Pull to refresh when the hub runs as a home-screen app (static/pull.js); also loaded by base.html.
PULL_JS = '<script src="/static/pull.js" defer></script>'


def _log_visit(user: str, slug: str) -> None:
    """Count an app open for the front page; never let it stop the app from opening."""
    try:
        with db() as con:
            home.record_visit(con, user, slug)
    except sqlite3.Error:
        log.warning("Could not log visit to %s", slug, exc_info=True)


@app.get("/go/{slug}")
def open_link(slug: str, user: str = Depends(require_user)):
    """Open an external link card, counting it like any other app."""
    link = next((a for a in list_artifacts(user) if a["slug"] == slug and a["kind"] == "link"), None)
    if not link:
        raise HTTPException(404)
    _log_visit(user, slug)
    return RedirectResponse(link["url"], status_code=302)


def _html_with_shim(path: Path, slug: str, user: str, *, with_banner: bool) -> HTMLResponse:
    """Serve an artifact page with static/hub.js injected first in <head>, so window.claude.use() exists,
    and the hub banner right after <body> unless the app has it turned off."""
    html = path.read_text("utf-8", errors="replace")
    strings = escape(json.dumps(i18n.js("js.hub.")), quote=True)
    tag = NO_SIDEWAYS_CSS + banner.CSS_HOST + '<script src="/static/hub.js" data-slug="{}" data-user="{}" data-admin="{}" data-strings="{}"></script>'.format(
        escape(slug), escape(user), "1" if is_admin(user) else "0", strings
    ) + PULL_JS
    app = next((a for a in list_artifacts(user) if a["slug"] == slug), None) if with_banner else None
    html = banner.inject(html, tag, banner.render(app, SITE_NAME) if app and app["banner"] else None)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- routes: document store (hub.js)
SEG_RE = re.compile(r"^[^/]{1,200}$")
MAX_DOC_BYTES = 256 * 1024


def _store_owner(slug: str, user: str) -> str:
    """The store is private per user; you need access to the artifact to use it."""
    found = artifact_root(slug)
    if not found or not can_see(found[1], user):
        raise HTTPException(404)
    return user.lower()


def _split_path(path: str, want_doc: bool) -> tuple[str, str]:
    """'a/b/c' -> collection 'a/b/c' (odd segments); 'a/b/c/d' -> ('a/b/c', 'd') (even segments)."""
    segs = [s for s in path.split("/") if s]
    if not segs or not all(SEG_RE.match(s) for s in segs) or (len(segs) % 2 == 0) != want_doc:
        raise HTTPException(400, i18n.t("store.bad_path", path=path))
    return ("/".join(segs[:-1]), segs[-1]) if want_doc else ("/".join(segs), "")


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@app.get("/api/store/{slug}/c")
def store_list(slug: str, path: str, user: str = Depends(require_user)):
    owner = _store_owner(slug, user)
    collection, _ = _split_path(path, want_doc=False)
    with db() as con:
        rows = con.execute(
            "SELECT doc_id, data FROM docs WHERE slug=? AND owner=? AND collection=? ORDER BY doc_id",
            (slug, owner, collection),
        ).fetchall()
    return {"docs": [{"id": r["doc_id"], "data": json.loads(r["data"])} for r in rows]}


@app.get("/api/store/{slug}/d")
def store_get(slug: str, path: str, user: str = Depends(require_user)):
    owner = _store_owner(slug, user)
    collection, doc_id = _split_path(path, want_doc=True)
    with db() as con:
        row = con.execute(
            "SELECT data FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?",
            (slug, owner, collection, doc_id),
        ).fetchone()
    return {"data": json.loads(row["data"]) if row else None}


@app.put("/api/store/{slug}/d")
async def store_set(slug: str, path: str, request: Request, merge: bool = False, user: str = Depends(require_user)):
    owner = _store_owner(slug, user)
    collection, doc_id = _split_path(path, want_doc=True)
    body = await request.body()
    if len(body) > MAX_DOC_BYTES:
        raise HTTPException(413, i18n.t("store.too_big"))
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, i18n.t("store.bad_json"))
    if not isinstance(data, dict):
        raise HTTPException(400, i18n.t("store.not_object"))
    with db() as con:
        row = con.execute(
            "SELECT data FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?",
            (slug, owner, collection, doc_id),
        ).fetchone()
        if merge:  # update() requires the document to exist
            if not row:
                raise HTTPException(404, i18n.t("store.doc_missing"))
            data = _deep_merge(json.loads(row["data"]), data)
        con.execute(
            """INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(slug, owner, collection, doc_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
            (slug, owner, collection, doc_id, json.dumps(data, ensure_ascii=False), int(time.time())),
        )
    return {"ok": True}


@app.delete("/api/store/{slug}/d")
def store_delete(slug: str, path: str, user: str = Depends(require_user)):
    owner = _store_owner(slug, user)
    collection, doc_id = _split_path(path, want_doc=True)
    with db() as con:
        con.execute(
            "DELETE FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?", (slug, owner, collection, doc_id)
        )
    return {"ok": True}


@app.get("/api/store/{slug}")
def store_dump(slug: str, user: str = Depends(require_user)):
    """Everything you have stored for one artifact, as {collection: {doc_id: data}} — a backup."""
    owner = _store_owner(slug, user)
    with db() as con:
        rows = con.execute(
            "SELECT collection, doc_id, data FROM docs WHERE slug=? AND owner=? ORDER BY collection, doc_id",
            (slug, owner),
        ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["collection"], {})[r["doc_id"]] = json.loads(r["data"])
    return out


# ---------------------------------------------------------------- shared data helpers (connector)
# The same documents an app reads and writes through window.claude.use("db") (hub.js), for one user.
MAX_DATA_DOCS_LISTED = 500


def _data_owner(slug: str, user: str) -> str:
    found = artifact_root(slug)
    if not found or not can_see(found[1], user):
        raise HubError(i18n.t("data.no_app", slug=slug))
    return user.lower()


def _data_path(path: str, want_doc: bool) -> tuple[str, str]:
    segs = [s for s in str(path).split("/") if s]
    if not segs or not all(SEG_RE.match(s) for s in segs) or (len(segs) % 2 == 0) != want_doc:
        raise HubError(i18n.t("data.bad_path_doc" if want_doc else "data.bad_path_col", path=path))
    return ("/".join(segs[:-1]), segs[-1]) if want_doc else ("/".join(segs), "")


def doc_overview(slug: str, user: str) -> dict[str, list[str]]:
    """{collection: [doc ids]} for everything the user has stored in one app."""
    owner = _data_owner(slug, user)
    with db() as con:
        rows = con.execute("SELECT collection, doc_id FROM docs WHERE slug=? AND owner=? ORDER BY collection, doc_id",
                           (slug, owner)).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["collection"], []).append(r["doc_id"])
    return out


def doc_list(slug: str, user: str, collection: str) -> dict[str, dict]:
    """{doc_id: data} for one collection (at most MAX_DATA_DOCS_LISTED, newest ids last)."""
    owner = _data_owner(slug, user)
    col, _ = _data_path(collection, want_doc=False)
    with db() as con:
        rows = con.execute("SELECT doc_id, data FROM docs WHERE slug=? AND owner=? AND collection=? ORDER BY doc_id",
                           (slug, owner, col)).fetchall()
    return {r["doc_id"]: json.loads(r["data"]) for r in rows[-MAX_DATA_DOCS_LISTED:]}


def doc_get(slug: str, user: str, path: str) -> dict | None:
    owner = _data_owner(slug, user)
    col, doc_id = _data_path(path, want_doc=True)
    with db() as con:
        row = con.execute("SELECT data FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?",
                          (slug, owner, col, doc_id)).fetchone()
    return json.loads(row["data"]) if row else None


def doc_set(slug: str, user: str, path: str, data: dict, *, merge: bool = False) -> dict:
    """Write one document (merge=True deep-merges into an existing one); returns what is stored now."""
    owner = _data_owner(slug, user)
    col, doc_id = _data_path(path, want_doc=True)
    if not isinstance(data, dict):
        raise HubError(i18n.t("data.not_object"))
    with db() as con:
        row = con.execute("SELECT data FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?",
                          (slug, owner, col, doc_id)).fetchone()
        if merge and row:
            data = _deep_merge(json.loads(row["data"]), data)
        raw = json.dumps(data, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_DOC_BYTES:
            raise HubError(i18n.t("data.too_big"))
        con.execute(
            """INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(slug, owner, collection, doc_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
            (slug, owner, col, doc_id, raw, int(time.time())),
        )
    log.info("Data %s %s/%s for %s", "merged" if merge else "set", slug, path, owner)
    return data


def doc_delete(slug: str, user: str, path: str) -> bool:
    owner = _data_owner(slug, user)
    col, doc_id = _data_path(path, want_doc=True)
    with db() as con:
        n = con.execute("DELETE FROM docs WHERE slug=? AND owner=? AND collection=? AND doc_id=?",
                        (slug, owner, col, doc_id)).rowcount
    return n > 0


# ---------------------------------------------------------------- routes: per-user app data
# Small key/value store so artifacts can keep data for the logged-in user.
# Every row belongs to one e-mail and one app name; a user can never read or write someone else's rows.
# Artifacts call it with same-origin fetch, so the session cookie is sent automatically.
#   GET    /api/me                          -> {"email", "admin"}
#   GET    /api/data/{app}?prefix=logs/     -> {"items": [{"key", "value", "updated"}]}
#   GET    /api/data/{app}/{key}            -> {"key", "value", "updated"}   (404 if missing)
#   PUT    /api/data/{app}/{key}   {"value": <json>}
#   DELETE /api/data/{app}/{key}
#   POST   /api/data/{app}/_batch  {"set": {key: value, ...}, "delete": [key, ...]}   (import, all or nothing)
DATA_KEY_RE = re.compile(r"^[A-Za-z0-9._:@+-]{1,100}(/[A-Za-z0-9._:@+-]{1,100}){0,4}$")
MAX_VALUE_BYTES = 512 * 1024          # per key
MAX_KEYS_PER_APP = 5000               # per user and app
MAX_BYTES_PER_APP = 25 * 1024 * 1024  # per user and app
MAX_BATCH = 2000


def api_user(request: Request) -> str:
    """Like require_user, but answers 401 JSON instead of redirecting to the login page."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail=i18n.t("err.not_logged_in"))
    return user


def _check_app_key(app_name: str, key: str | None = None) -> None:
    if not SLUG_RE.match(app_name):
        raise HTTPException(400, i18n.t("store.bad_app"))
    if key is not None and not DATA_KEY_RE.match(key):
        raise HTTPException(400, i18n.t("store.bad_key"))


def _require_json(request: Request) -> None:
    # A JSON content type cannot be sent cross-site without a CORS preflight, which this app never allows.
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        raise HTTPException(415, i18n.t("store.need_json"))


def _encode_value(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_VALUE_BYTES:
        raise HTTPException(413, i18n.t("store.value_big"))
    return raw


def _check_quota(con: sqlite3.Connection, email: str, app_name: str, new_rows: dict[str, str], deleted: set[str] = frozenset()) -> None:
    rows = con.execute("SELECT key, LENGTH(value) AS n FROM app_data WHERE email=? AND app=?", (email, app_name)).fetchall()
    sizes = {r["key"]: r["n"] for r in rows if r["key"] not in deleted}
    for k, v in new_rows.items():
        sizes[k] = len(v.encode("utf-8"))
    if len(sizes) > MAX_KEYS_PER_APP:
        raise HTTPException(413, i18n.t("store.too_many_keys"))
    if sum(sizes.values()) > MAX_BYTES_PER_APP:
        raise HTTPException(413, i18n.t("store.full"))


@app.get("/api/me")
def api_me(user: str = Depends(api_user)):
    return {"email": user, "admin": is_admin(user)}


# ---------------------------------------------------------------- routes: front page prefs (app/home.py)
@app.post("/api/prefs/view")
async def prefs_view(request: Request, user: str = Depends(api_user)):
    _require_json(request)
    body = await request.json()
    view = body.get("view") if isinstance(body, dict) else None
    with db() as con:
        try:
            home.set_view(con, user, view)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "view": view}


@app.post("/api/prefs/pin")
async def prefs_pin(request: Request, user: str = Depends(api_user)):
    _require_json(request)
    body = await request.json()
    slug, pinned = (body.get("slug"), body.get("pinned")) if isinstance(body, dict) else (None, None)
    if not isinstance(slug, str) or not isinstance(pinned, bool):
        raise HTTPException(400, 'Send {"slug": "...", "pinned": true|false}')
    if slug not in {a["slug"] for a in list_artifacts(user)}:
        raise HTTPException(404)
    with db() as con:
        pins = home.set_pin(con, user, slug, pinned)
    return {"ok": True, "pins": pins}


@app.post("/api/prefs/apps")
async def prefs_apps(request: Request, user: str = Depends(api_user)):
    """Add an app to, or take it off, the user's front page."""
    _require_json(request)
    body = await request.json()
    slug, added = (body.get("slug"), body.get("added")) if isinstance(body, dict) else (None, None)
    if not isinstance(slug, str) or not isinstance(added, bool):
        raise HTTPException(400, 'Send {"slug": "...", "added": true|false}')
    if slug not in {a["slug"] for a in list_artifacts(user)}:
        raise HTTPException(404)
    with db() as con:
        apps = home.set_added(con, user, slug, added)
    return {"ok": True, "apps": apps}


@app.post("/api/prefs/seen")
def prefs_seen(request: Request, user: str = Depends(api_user)):
    """The user opened the "Velg apper" list: nothing in it is new any more."""
    _require_json(request)
    with db() as con:
        home.mark_seen(con, user, [a["slug"] for a in list_artifacts(user)])
    return {"ok": True}


@app.get("/api/data/{app_name}")
def data_list(app_name: str, prefix: str = "", user: str = Depends(api_user)):
    _check_app_key(app_name)
    like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db() as con:
        rows = con.execute(
            "SELECT key, value, updated FROM app_data WHERE email=? AND app=? AND key LIKE ? ESCAPE '\\' ORDER BY key",
            (user, app_name, like),
        ).fetchall()
    return {"items": [{"key": r["key"], "value": json.loads(r["value"]), "updated": r["updated"]} for r in rows]}


@app.post("/api/data/{app_name}/_batch")
async def data_batch(app_name: str, request: Request, user: str = Depends(api_user)):
    _check_app_key(app_name)
    _require_json(request)
    body = await request.json()
    to_set = body.get("set") or {}
    to_del = body.get("delete") or []
    if not isinstance(to_set, dict) or not isinstance(to_del, list) or len(to_set) + len(to_del) > MAX_BATCH:
        raise HTTPException(400, i18n.t("store.bad_batch"))
    for k in list(to_set) + to_del:
        _check_app_key(app_name, k)
    encoded = {k: _encode_value(v) for k, v in to_set.items()}
    now = int(time.time())
    with db() as con:  # one transaction: all or nothing
        _check_quota(con, user, app_name, encoded, set(to_del))
        con.executemany("DELETE FROM app_data WHERE email=? AND app=? AND key=?", [(user, app_name, k) for k in to_del])
        con.executemany(
            "INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(email, app, key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            [(user, app_name, k, v, now) for k, v in encoded.items()],
        )
    return {"ok": True, "set": len(encoded), "deleted": len(to_del), "updated": now}


@app.get("/api/data/{app_name}/{key:path}")
def data_get(app_name: str, key: str, user: str = Depends(api_user)):
    _check_app_key(app_name, key)
    with db() as con:
        r = con.execute("SELECT value, updated FROM app_data WHERE email=? AND app=? AND key=?", (user, app_name, key)).fetchone()
    if not r:
        raise HTTPException(404, i18n.t("store.not_found"))
    return {"key": key, "value": json.loads(r["value"]), "updated": r["updated"]}


@app.put("/api/data/{app_name}/{key:path}")
async def data_put(app_name: str, key: str, request: Request, user: str = Depends(api_user)):
    _check_app_key(app_name, key)
    _require_json(request)
    body = await request.json()
    if not isinstance(body, dict) or "value" not in body:
        raise HTTPException(400, 'Send {"value": ...}')
    raw = _encode_value(body["value"])
    now = int(time.time())
    with db() as con:
        _check_quota(con, user, app_name, {key: raw})
        con.execute(
            "INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(email, app, key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            (user, app_name, key, raw, now),
        )
    return {"ok": True, "updated": now}


@app.delete("/api/data/{app_name}/{key:path}")
def data_delete(app_name: str, key: str, request: Request, user: str = Depends(api_user)):
    _check_app_key(app_name, key)
    with db() as con:
        con.execute("DELETE FROM app_data WHERE email=? AND app=? AND key=?", (user, app_name, key))
    return {"ok": True}


# ---------------------------------------------------------------- routes: admin / upload
def _upload_authorized(request: Request) -> str:
    """Either an admin session cookie, or a bearer token (for push.sh)."""
    auth_header = request.headers.get("authorization", "")
    if UPLOAD_TOKEN and auth_header == f"Bearer {UPLOAD_TOKEN}":
        return "token"
    return require_admin(request)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.")
    return s[:80] or "artifact"


def _new_app(slug: str) -> None:
    """A brand-new app goes straight onto the admins' front pages (others pick it from their list)."""
    with db() as con:
        home.add_for(con, ADMIN_EMAILS, slug)


def _save_upload(upload: UploadFile, slug: str | None, admin_only: bool, title: str | None) -> str:
    filename = upload.filename or "artifact"
    stem, ext = os.path.splitext(filename)
    slug = _slugify(slug or stem)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, i18n.t("err.invalid_name", name=slug))
    # a new version keeps the old name, emoji, private flag and banner switch (stored as false) unless overridden
    old = _meta_path(slug)
    is_new = old is None
    old_meta = _read_meta(old) if old else {}
    meta = {k: old_meta[k] for k in META_KEYS if old_meta.get(k) or old_meta.get(k) is False}
    if title:
        meta["title"] = title
    if admin_only:
        meta["admin_only"] = True
    versions.save(ARTIFACTS_DIR, slug)  # keep the previous version before replacing it
    # remove any existing artifact with that slug
    for old in (ARTIFACTS_DIR / f"{slug}.html", ARTIFACTS_DIR / f"{slug}.meta.json"):
        old.unlink(missing_ok=True)
    if (ARTIFACTS_DIR / slug).is_dir():
        shutil.rmtree(ARTIFACTS_DIR / slug)

    if ext.lower() == ".zip":
        dest = ARTIFACTS_DIR / slug
        dest.mkdir()
        with zipfile.ZipFile(upload.file) as z:
            for member in z.infolist():
                target = (dest / member.filename).resolve()
                if dest.resolve() not in target.parents:
                    raise HTTPException(400, i18n.t("err.zip_paths"))
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        # allow zips that contain a single top-level folder
        if not (dest / "index.html").exists():
            subs = [p for p in dest.iterdir() if p.is_dir()]
            if len(subs) == 1 and (subs[0] / "index.html").exists():
                for item in subs[0].iterdir():
                    shutil.move(str(item), dest / item.name)
                subs[0].rmdir()
        if not (dest / "index.html").exists():
            shutil.rmtree(dest)
            raise HTTPException(400, i18n.t("err.zip_index"))
        if meta:
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    elif ext.lower() in (".html", ".htm"):
        dest = ARTIFACTS_DIR / f"{slug}.html"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        if meta:
            (ARTIFACTS_DIR / f"{slug}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        raise HTTPException(400, i18n.t("err.upload_type"))
    if is_new:
        _new_app(slug)
    log.info("Uploaded artifact %s", slug)
    return slug


# ---------------------------------------------------------------- shared write helpers
MAX_PAGE_BYTES = 1024 * 1024
_HTML_HINT = re.compile(r"<html|<!doctype html|<body", re.I)


class HubError(Exception):
    """A problem with a write; the message is text in the hub's language (HUB_LANG) shown to the user."""


def _write_meta(path: Path, meta: dict) -> None:
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def _apply_info(meta: dict, title: str | None, description: str | None, emoji: str | None) -> None:
    """None leaves a field alone; an empty value removes it."""
    for key, value in (("title", title), ("description", description), ("emoji", emoji)):
        if value is None:
            continue
        value = value.strip()[:16] if key == "emoji" else value.strip()
        if value:
            meta[key] = value
        else:
            meta.pop(key, None)


def _check_html(html: str) -> None:
    if len(html.encode("utf-8")) > MAX_PAGE_BYTES:
        raise HubError(i18n.t("page.too_big", kb=MAX_PAGE_BYTES // 1024))
    if not _HTML_HINT.search(html):
        raise HubError(i18n.t("page.not_html"))


def _single_page(slug: str) -> Path:
    """The editable HTML of an existing app: the page itself, or index.html of a folder app. HubError otherwise."""
    meta_path = _meta_path(slug)
    if not meta_path:
        raise HubError(i18n.t("page.not_found", slug=slug))
    if meta_path.name.endswith(".link.json"):
        raise HubError(i18n.t("page.is_link", slug=slug))
    if meta_path.name == "meta.json":
        return ARTIFACTS_DIR / slug / "index.html"  # folder app: only index.html is edited, its other files stay
    return ARTIFACTS_DIR / f"{slug}.html"


def save_page(slug: str, html: str, *, create: bool, title: str | None = None, description: str | None = None,
              emoji: str | None = None, private: bool | None = None) -> str:
    """Create a single-file page (private unless said otherwise), or replace the HTML of an existing page or
    folder app (its index.html); returns the slug."""
    if not SLUG_RE.match(slug):
        raise HubError(i18n.t("page.bad_slug", slug=slug))
    _check_html(html)
    if create:
        if _meta_path(slug):
            raise HubError(i18n.t("page.exists", slug=slug))
        meta: dict = {}
        if private is None:
            private = True
        dest, meta_path = ARTIFACTS_DIR / f"{slug}.html", ARTIFACTS_DIR / f"{slug}.meta.json"
    else:
        dest, meta_path = _single_page(slug), _meta_path(slug)  # a folder app gets a new index.html
        meta = _read_meta(meta_path)
        versions.save(ARTIFACTS_DIR, slug)  # keep the previous version before replacing it
    _apply_info(meta, title, description, emoji)
    if private is not None:
        access.set_level(meta, "admin" if private else "all")
    dest.write_text(html, "utf-8")
    _write_meta(meta_path, meta)
    if create:
        _new_app(slug)
    log.info("%s page %s", "Created" if create else "Updated", slug)
    return slug


def edit_page(slug: str, edits: list[tuple[str, str]]) -> None:
    """Replace exact snippets in a page. Each must match exactly once; all or nothing."""
    dest = _single_page(slug)
    text = dest.read_text("utf-8")
    for n, (old, new) in enumerate(edits, 1):
        count = text.count(old) if old else 0
        if count == 0:
            raise HubError(i18n.t("page.edit_missing", n=n))
        if count > 1:
            raise HubError(i18n.t("page.edit_multi", n=n, count=count))
        text = text.replace(old, new, 1)
    _check_html(text)
    versions.save(ARTIFACTS_DIR, slug)
    dest.write_text(text, "utf-8")
    log.info("Edited page %s (%d edits)", slug, len(edits))


def set_info(slug: str, *, title: str | None = None, description: str | None = None, emoji: str | None = None,
             private: bool | None = None) -> None:
    """Change gallery info for a page or link card. None = unchanged, "" = remove the field."""
    meta_path = _meta_path(slug)
    if not meta_path:
        raise HubError(i18n.t("page.not_found", slug=slug))
    meta = _read_meta(meta_path)
    _apply_info(meta, title, description, emoji)
    if private is not None:
        access.set_level(meta, "admin" if private else "all")
    _write_meta(meta_path, meta)


def page_source(slug: str) -> str:
    """The page as stored, without the hub.js shim."""
    return _single_page(slug).read_text("utf-8")


def known_people() -> list[str]:
    """E-mails offered in the access dialog: invited, ALLOWED_EMAILS, anyone who has logged in and everyone
    on an app's list. Admins always have access, so they are left out."""
    with db() as con:
        found = set(access.invited(con)) | {access.norm(r[0]) for r in con.execute("SELECT DISTINCT email FROM logins")}
    found |= ALLOWED_EMAILS
    for slug in _all_slugs():
        found |= set(access.people(_read_meta(_meta_path(slug))))
    return sorted(found - ADMIN_EMAILS)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: str = Depends(require_admin)):
    with db() as con:
        invited = set(access.invited(con))
    # "Fjern" only for those an invitation lets in; ALLOWED_EMAILS are let in by the server config
    shown = (invited | ALLOWED_EMAILS) - ADMIN_EMAILS
    if password_mode():
        shown |= ADMIN_EMAILS - {access.norm(user)}  # other admins may need a password too
    people = [{"email": e, "invited": e in invited and e not in ALLOWED_EMAILS, "admin": e in ADMIN_EMAILS}
              for e in sorted(shown)]
    if password_mode():
        with db() as con:
            for p in people:
                row = passwd.get(con, p["email"])
                p["pw_status"] = "missing" if row is None else ("must_change" if row["must_change"] else "set")
    return templates.TemplateResponse(
        request, "admin.html", {"site": SITE_NAME, "user": user, "admin": True, "artifacts": list_artifacts(user),
                                "known": known_people(), "people": people}
    )


def _ago(ts: int, now: int) -> str:
    """How long ago, without a clock time (the server's time zone may not be the viewer's)."""
    secs = max(0, now - ts)
    if secs < 3600:
        return i18n.t("time.ago_min", n=max(1, secs // 60))
    if secs < 86400:
        return i18n.t("time.ago_hours", n=secs // 3600)
    return i18n.t("time.ago_days", n=secs // 86400)


@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats(request: Request, user: str = Depends(require_admin)):
    """Who opened which apps in the last 7 days; admins are left out."""
    with db() as con:
        stats = home.week_stats(con, exclude=ADMIN_EMAILS)
    known = {a["slug"]: a for a in list_artifacts(user)}
    now = int(time.time())
    for u in stats["users"]:
        u["ago"] = _ago(u["last"], now)
    top = max((a["opens"] for a in stats["apps"]), default=0)
    for a in stats["apps"]:
        a["app"] = known.get(a["slug"])  # None for an app that has been deleted since
        a["width"] = round(100 * a["opens"] / top) if top else 0
    used = {a["slug"] for a in stats["apps"]}
    return templates.TemplateResponse(
        request, "admin_stats.html",
        {"site": SITE_NAME, "user": user, "admin": True, "stats": stats,
         "idle": [a for a in known.values() if a["slug"] not in used],
         "titles": {slug: a["title"] for slug, a in known.items()}},
    )


@app.post("/api/upload")
async def api_upload(
    request: Request,
    file: UploadFile = File(...),
    slug: str | None = Form(None),
    title: str | None = Form(None),
    admin_only: bool = Form(False),
):
    _upload_authorized(request)
    saved = _save_upload(file, slug, admin_only, title)
    return JSONResponse({"ok": True, "slug": saved, "url": f"{BASE_URL}/a/{saved}/"})


@app.post("/api/delete")
def api_delete(request: Request, slug: str = Form(...)):
    _upload_authorized(request)
    if not SLUG_RE.match(slug):
        raise HTTPException(400)
    removed = False
    for p in (ARTIFACTS_DIR / f"{slug}.html", ARTIFACTS_DIR / f"{slug}.meta.json", ARTIFACTS_DIR / f"{slug}.link.json"):
        if p.exists():
            p.unlink()
            removed = True
    if (ARTIFACTS_DIR / slug).is_dir():
        shutil.rmtree(ARTIFACTS_DIR / slug)
        removed = True
    if not removed:
        raise HTTPException(404)
    _remove_icon(slug)
    return JSONResponse({"ok": True})


@app.post("/api/access")
async def api_access(request: Request, user: str = Depends(require_admin)):
    """Who may see an app: {"slug", "level": "all" | "people" | "admin", "people": [e-mails]}.
    The list is kept whatever the level; with "people" everyone on it is also invited (may log in)."""
    _require_json(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, 'Send {"slug", "level", "people"}')
    slug, level, people = body.get("slug"), body.get("level"), body.get("people", [])
    meta_path = _meta_path(slug) if isinstance(slug, str) else None
    if not meta_path:
        raise HTTPException(404)
    if level not in access.LEVELS:
        raise HTTPException(400, i18n.t("access.unknown", level=level))
    if not isinstance(people, list) or not all(isinstance(e, str) for e in people):
        raise HTTPException(400, i18n.t("err.people_list"))
    bad = [e for e in people if not EMAIL_RE.match(access.norm(e))]
    if bad:
        raise HTTPException(400, i18n.t("err.emails_invalid", emails=", ".join(bad)))
    people = [e for e in access.people({"people": people}) if e not in ADMIN_EMAILS]
    meta = _read_meta(meta_path)
    access.set_level(meta, level, people)
    _write_meta(meta_path, meta)
    if level == "people":
        with db() as con:
            for e in people:
                if not allowed_by_config(e):  # already let in by the server config: no invitation to take back
                    access.invite(con, e)
    return {"ok": True, "level": level, "label": access.label(meta)}


@app.post("/api/toggle-banner")
def api_toggle_banner(request: Request, slug: str = Form(...)):
    """Turn the hub banner off or on for one app; off is stored as "banner": false, on removes the key."""
    _upload_authorized(request)
    meta_path = _meta_path(slug)
    if not meta_path or meta_path.name.endswith(".link.json"):
        raise HTTPException(404)
    meta = _read_meta(meta_path)
    if meta.get("banner") is False:
        meta.pop("banner")
    else:
        meta["banner"] = False
    _write_meta(meta_path, meta)
    return JSONResponse({"ok": True, "banner": meta.get("banner") is not False})


# ---------------------------------------------------------------- routes: invited people (app/access.py)
def _all_slugs() -> list[str]:
    """Every app and link card in the data dir."""
    slugs = set()
    for p in ARTIFACTS_DIR.iterdir():
        name = p.name
        if name.startswith("."):
            continue
        if name.endswith(".link.json"):
            slugs.add(name[: -len(".link.json")])
        elif p.is_file() and name.endswith(".html"):
            slugs.add(name[: -len(".html")])
        elif p.is_dir() and (p / "index.html").is_file():
            slugs.add(name)
    return sorted(s for s in slugs if SLUG_RE.match(s))  # a file copied in by hand may not be a valid slug


def remove_person(email: str) -> list[str]:
    """Take back an invitation and take the e-mail off every app's list; returns the apps it was on."""
    email = access.norm(email)
    with db() as con:
        access.uninvite(con, email)
    removed = []
    for slug in _all_slugs():
        meta_path = _meta_path(slug)
        meta = _read_meta(meta_path) if meta_path else {}
        if email in access.people(meta):
            access.set_level(meta, access.level(meta), [e for e in access.people(meta) if e != email])
            _write_meta(meta_path, meta)
            removed.append(slug)
    return removed


async def _email_in(request: Request) -> str:
    """The trimmed, lower-case "email" of a JSON body; 400 if it is not an e-mail address."""
    _require_json(request)
    body = await request.json()
    email = access.norm(body["email"]) if isinstance(body, dict) and isinstance(body.get("email"), str) else ""
    if not EMAIL_RE.match(email):
        raise HTTPException(400, i18n.t("err.email_invalid"))
    return email


async def _email_and_password_in(request: Request) -> tuple[str, str | None]:
    """Like _email_in, plus the optional "password" (None unless it is a string)."""
    email = await _email_in(request)
    body = await request.json()
    pw = body.get("password")
    return email, pw if isinstance(pw, str) else None


def _check_temp_password(pw: str | None) -> str:
    if pw is None or not 10 <= len(pw) <= 200:
        raise HTTPException(400, i18n.t("err.temp_pw"))
    return pw


@app.post("/api/people/invite")
async def people_invite(request: Request, user: str = Depends(require_admin)):
    email, pw = await _email_and_password_in(request)
    if email in ADMIN_EMAILS:
        raise HTTPException(400, i18n.t("err.admin_always"))
    if password_mode():
        pw = _check_temp_password(pw)  # before inviting: a 400 must leave nobody invited
    with db() as con:
        access.invite(con, email)
        if password_mode():
            passwd.set_password(con, email, pw, must_change=True)
    return {"ok": True, "email": email}


@app.post("/api/people/password")
async def people_password(request: Request, user: str = Depends(require_admin)):
    """Set a new temporary password for someone who may log in (password mode only)."""
    if not password_mode():
        raise HTTPException(404, i18n.t("err.not_in_use"))
    email, pw = await _email_and_password_in(request)
    pw = _check_temp_password(pw)
    if not email_allowed(email):
        raise HTTPException(404, i18n.t("err.not_invited"))
    with db() as con:
        passwd.set_password(con, email, pw, must_change=True)
    return {"ok": True, "email": email}


@app.post("/api/people/remove")
async def people_remove(request: Request, user: str = Depends(require_admin)):
    email = await _email_in(request)
    with db() as con:
        if not access.is_invited(con, email):
            raise HTTPException(404, i18n.t("err.not_invited"))
    apps = remove_person(email)
    with db() as con:
        passwd.delete(con, email)
    return {"ok": True, "apps": apps}


def _check_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://[^\s/]+\.[^\s]+$", url):
        raise HTTPException(400, i18n.t("err.url"))
    return url


@app.post("/api/link")
def api_link(
    request: Request,
    title: str = Form(...),
    url: str = Form(...),
    admin_only: bool = Form(False),
):
    """Add an external link card (like recall.link.json) to the gallery."""
    _upload_authorized(request)
    title, url = title.strip(), _check_url(url)
    if not title:
        raise HTTPException(400, i18n.t("err.link_name"))
    slug = _slugify(title)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, i18n.t("err.invalid_name", name=title))
    if _meta_path(slug):
        raise HTTPException(409, i18n.t("err.exists", slug=slug))
    meta = {"title": title, "url": url}
    if admin_only:
        meta["admin_only"] = True
    (ARTIFACTS_DIR / f"{slug}.link.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    _new_app(slug)
    log.info("Added link card %s -> %s", slug, url)
    return JSONResponse({"ok": True, "slug": slug})


@app.post("/api/edit")
async def api_edit(
    request: Request,
    slug: str = Form(...),
    new_slug: str = Form(""),
    title: str = Form(""),
    emoji: str = Form(""),
    icon: UploadFile | None = File(None),
    remove_icon: bool = Form(False),
    url: str = Form(""),
):
    """Rename (title and/or address) and set the icon of an artifact or link card."""
    _upload_authorized(request)
    meta_path = _meta_path(slug)
    if not meta_path:
        raise HTTPException(404)
    new_slug = _slugify(new_slug) if new_slug.strip() else slug
    if not SLUG_RE.match(new_slug):
        raise HTTPException(400, i18n.t("err.address_invalid", slug=new_slug))
    if new_slug != slug and _meta_path(new_slug):
        raise HTTPException(409, i18n.t("err.address_taken", slug=new_slug))

    icon_data, icon_ext = None, ""
    if icon and icon.filename:
        icon_ext = os.path.splitext(icon.filename)[1].lower()
        if icon_ext not in ICON_TYPES:
            raise HTTPException(400, i18n.t("err.icon_type"))
        icon_data = await icon.read(MAX_ICON_BYTES + 1)
        if len(icon_data) > MAX_ICON_BYTES:
            raise HTTPException(400, i18n.t("err.icon_size"))

    is_link = meta_path.name.endswith(".link.json")
    if is_link and url.strip():
        url = _check_url(url)

    meta = _read_meta(meta_path)
    if is_link and url:
        meta["url"] = url
    _apply_info(meta, title, None, emoji)  # empty title -> falls back to <title> in the HTML
    _write_meta(meta_path, meta)

    if remove_icon or icon_data:
        _remove_icon(slug)
    if icon_data:
        ICONS_DIR.mkdir(exist_ok=True)
        (ICONS_DIR / f"{slug}{icon_ext}").write_bytes(icon_data)

    if new_slug != slug:
        versions.rename(ARTIFACTS_DIR, slug, new_slug)
        moves = [(ARTIFACTS_DIR / f"{slug}{suffix}", ARTIFACTS_DIR / f"{new_slug}{suffix}")
                 for suffix in (".html", ".meta.json", ".link.json", "")]
        if old_icon := _icon_file(slug):
            moves.append((old_icon, ICONS_DIR / f"{new_slug}{old_icon.suffix}"))
        for src, dst in moves:
            if src.exists():
                src.rename(dst)
        with db() as con:  # users' stored data, choices and pins follow the artifact
            con.execute("UPDATE OR REPLACE docs SET slug=? WHERE slug=?", (new_slug, slug))
            home.rename(con, slug, new_slug)
        log.info("Renamed artifact %s -> %s", slug, new_slug)
    return JSONResponse({"ok": True, "slug": new_slug})


@app.get("/icon/{slug}")
def serve_icon(slug: str, user: str = Depends(require_user)):
    meta_path = _meta_path(slug)
    icon = _icon_file(slug) if meta_path else None
    if not icon or not can_see(_read_meta(meta_path), user):
        raise HTTPException(404)
    # an SVG opened directly must not be able to run scripts on this origin
    return FileResponse(icon, media_type=ICON_TYPES[icon.suffix],
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # browsers ask for /favicon.ico on pages without <link rel=icon> (e.g. artifacts)
    return FileResponse(static_file("favicon-32.png"), media_type="image/png")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------------------------------------------------------- Claude connector (OAuth)
from app import oauth  # noqa: E402  (imports this module, so it must come last)

app.include_router(oauth.router)

# ---------------------------------------------------------------- Claude connector (MCP)
from app import connector  # noqa: E402

connector_app = connector.Connector()
app.router.lifespan_context = connector_app.lifespan  # runs the MCP session manager
app.mount("/", connector_app)  # last, so every FastAPI route above wins
