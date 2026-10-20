"""
Artifact Hub — host Claude artifacts behind a magic-link login.

Layout of the data dir (ARTIFACTS_DIR, default /data/artifacts):
    my-chart.html                  -> served at /a/my-chart/
    my-app/index.html (+ assets)   -> served at /a/my-app/
    my-chart.meta.json             -> optional: {"title": "...", "description": "...", "admin_only": true}
    my-app/meta.json               -> same, for folder artifacts
    recall.link.json               -> external link card: {"title": "...", "url": "...", "admin_only": true}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import smtplib
import sqlite3
import time
import zipfile
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------- config
BASE_DIR = Path(__file__).parent
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/data/artifacts"))
DB_PATH = Path(os.environ.get("DB_PATH", "/data/hub.db"))
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
SITE_NAME = os.environ.get("SITE_NAME", "Artifact Hub")

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
ALLOWED_EMAILS = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
ALLOWED_DOMAINS = {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()}
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")  # for scripts/push.sh

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "hub@localhost")
SMTP_TLS = os.environ.get("SMTP_TLS", "starttls")  # starttls | ssl | none

MAGIC_TTL = 15 * 60               # seconds a magic link is valid
SESSION_TTL = 30 * 24 * 3600      # seconds a session cookie lives
COOKIE = "hub_session"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["strftime"] = lambda ts: time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))
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


# ---------------------------------------------------------------- auth helpers
def email_allowed(email: str) -> bool:
    email = email.lower()
    if email in ADMIN_EMAILS or email in ALLOWED_EMAILS:
        return True
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return domain in ALLOWED_DOMAINS


def is_admin(email: str | None) -> bool:
    return bool(email) and email.lower() in ADMIN_EMAILS


def current_user(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        return signer.loads(raw, max_age=SESSION_TTL)["email"]
    except (BadSignature, KeyError):
        return None


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
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def send_magic_link(email: str, link: str) -> None:
    if not SMTP_HOST:
        log.warning("SMTP not configured — magic link for %s: %s", email, link)
        return
    msg = EmailMessage()
    msg["Subject"] = f"Logg inn på {SITE_NAME}"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(
        f"Hei!\n\nKlikk lenken for å logge inn på {SITE_NAME} (gyldig i 15 minutter):\n\n{link}\n\n"
        f"Hvis du ikke ba om dette kan du ignorere e-posten."
    )
    if SMTP_TLS == "ssl":
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        if SMTP_TLS == "starttls":
            server.starttls()
    with server:
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


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
        if meta.get("admin_only") and not admin:
            continue
        items.append(
            {
                "slug": slug,
                "kind": kind,
                "url": url,
                "title": meta.get("title") or fallback,
                "description": meta.get("description", ""),
                "admin_only": bool(meta.get("admin_only")),
                "updated": mtime,
            }
        )
    items.sort(key=lambda a: a["updated"], reverse=True)
    return items


def artifact_root(slug: str) -> tuple[Path, bool] | None:
    """Return (path, admin_only) for a slug, or None."""
    if not SLUG_RE.match(slug):
        return None
    f = ARTIFACTS_DIR / f"{slug}.html"
    if f.is_file():
        return f, bool(_read_meta(ARTIFACTS_DIR / f"{slug}.meta.json").get("admin_only"))
    d = ARTIFACTS_DIR / slug
    if d.is_dir() and (d / "index.html").is_file():
        return d, bool(_read_meta(d / "meta.json").get("admin_only"))
    return None


# ---------------------------------------------------------------- routes: auth
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    next = safe_next(next)
    if current_user(request):
        return RedirectResponse(next, status_code=302)
    return templates.TemplateResponse(request, "login.html", {"site": SITE_NAME, "sent": False, "next": next})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), next: str = Form("/")):
    email = email.strip().lower()
    next = safe_next(next)
    # Always show "sent" so we don't leak who is on the allowlist.
    if email_allowed(email):
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
    return templates.TemplateResponse(request, "login.html", {"site": SITE_NAME, "sent": True, "email": email})


@app.get("/auth")
def auth(token: str, next: str = "/"):
    h = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with db() as con:
        row = con.execute("SELECT email, expires_at, used FROM magic_tokens WHERE token_hash=?", (h,)).fetchone()
        if not row or row["used"] or row["expires_at"] < now:
            raise HTTPException(status_code=400, detail="Lenken er ugyldig eller utløpt. Be om en ny.")
        con.execute("UPDATE magic_tokens SET used=1 WHERE token_hash=?", (h,))
        con.execute("DELETE FROM magic_tokens WHERE expires_at < ?", (now,))
        con.execute("INSERT INTO logins(email, at) VALUES(?,?)", (row["email"], now))
    resp = RedirectResponse(safe_next(next), status_code=302)
    resp.set_cookie(
        COOKIE,
        signer.dumps({"email": row["email"]}),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=BASE_URL.startswith("https://"),
    )
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


# ---------------------------------------------------------------- routes: gallery + serving
@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: str = Depends(require_user)):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"site": SITE_NAME, "user": user, "admin": is_admin(user), "artifacts": list_artifacts(user)},
    )


@app.get("/a/{slug}")
def artifact_redirect(slug: str):
    return RedirectResponse(f"/a/{slug}/", status_code=301)


@app.get("/a/{slug}/{path:path}")
def serve_artifact(slug: str, path: str, user: str = Depends(require_user)):
    found = artifact_root(slug)
    if not found:
        raise HTTPException(404)
    root, admin_only = found
    if admin_only and not is_admin(user):
        raise HTTPException(404)
    if root.is_file():
        if path not in ("", "index.html"):
            raise HTTPException(404)
        return FileResponse(root, media_type="text/html")
    target = (root / (path or "index.html")).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise HTTPException(404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file() or target.name == "meta.json":
        raise HTTPException(404)
    return FileResponse(target)


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


def _save_upload(upload: UploadFile, slug: str | None, admin_only: bool, title: str | None) -> str:
    filename = upload.filename or "artifact"
    stem, ext = os.path.splitext(filename)
    slug = _slugify(slug or stem)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, f"Ugyldig navn: {slug}")
    # remove any existing artifact with that slug
    for old in (ARTIFACTS_DIR / f"{slug}.html", ARTIFACTS_DIR / f"{slug}.meta.json"):
        old.unlink(missing_ok=True)
    if (ARTIFACTS_DIR / slug).is_dir():
        shutil.rmtree(ARTIFACTS_DIR / slug)

    meta = {k: v for k, v in {"title": title, "admin_only": admin_only or None}.items() if v}

    if ext.lower() == ".zip":
        dest = ARTIFACTS_DIR / slug
        dest.mkdir()
        with zipfile.ZipFile(upload.file) as z:
            for member in z.infolist():
                target = (dest / member.filename).resolve()
                if dest.resolve() not in target.parents:
                    raise HTTPException(400, "Zip inneholder ugyldige stier")
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
            raise HTTPException(400, "Zip må inneholde en index.html")
        if meta:
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    elif ext.lower() in (".html", ".htm"):
        dest = ARTIFACTS_DIR / f"{slug}.html"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        if meta:
            (ARTIFACTS_DIR / f"{slug}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        raise HTTPException(400, "Bare .html eller .zip (med index.html) støttes")
    log.info("Uploaded artifact %s", slug)
    return slug


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: str = Depends(require_admin)):
    return templates.TemplateResponse(
        request, "admin.html", {"site": SITE_NAME, "user": user, "admin": True, "artifacts": list_artifacts(user)}
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
    return JSONResponse({"ok": True})


@app.post("/api/toggle-private")
def api_toggle_private(request: Request, slug: str = Form(...)):
    _upload_authorized(request)
    found = artifact_root(slug)
    link = ARTIFACTS_DIR / f"{slug}.link.json"
    if found:
        root, _ = found
        meta_path = (ARTIFACTS_DIR / f"{slug}.meta.json") if root.is_file() else (root / "meta.json")
    elif link.exists():
        meta_path = link
    else:
        raise HTTPException(404)
    meta = _read_meta(meta_path)
    meta["admin_only"] = not meta.get("admin_only", False)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return JSONResponse({"ok": True, "admin_only": meta["admin_only"]})


@app.get("/healthz")
def healthz():
    return {"ok": True}
