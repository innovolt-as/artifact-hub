"""Shared fixtures. app.main reads its config at import time, so set the env first."""
import asyncio
import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="hub-test-"))
os.environ.update(
    ARTIFACTS_DIR=str(_tmp / "artifacts"),
    DB_PATH=str(_tmp / "hub.db"),
    BRANDING_DIR=str(_tmp / "branding"),
    ADMIN_EMAILS="admin@test.no",
    ALLOWED_EMAILS="user@test.no",
    BASE_URL="https://hub.test",
    SECRET_KEY="test",
)
os.environ.pop("UPLOAD_TOKEN", None)
os.environ.pop("ALLOWED_DOMAINS", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    """Empty the artifacts dir and the DB tables before each test."""
    for p in main.ARTIFACTS_DIR.iterdir():
        if p.is_dir():
            main.shutil.rmtree(p)
        else:
            p.unlink()
    if main.BRANDING_DIR.exists():
        main.shutil.rmtree(main.BRANDING_DIR)
    with main.db() as con:
        for table in ("magic_tokens", "logins", "docs", "app_data",
                      "oauth_clients", "oauth_requests", "oauth_codes", "oauth_tokens", "visits", "prefs", "invites", "passwords"):
            con.execute(f"DELETE FROM {table}")
    main._ip_sends.clear()
    yield


@pytest.fixture
def hub():
    return main


def make_client(email: str | None = None) -> TestClient:
    """A TestClient (https, so the secure cookie is sent), logged in as `email` if given."""
    c = TestClient(main.app, base_url="https://hub.test", follow_redirects=False)
    if email:
        c.cookies.set(main.COOKIE, main.signer.dumps({"email": email}))
    return c


@pytest.fixture
def client():
    return make_client()


@pytest.fixture
def admin_client():
    return make_client("admin@test.no")


@pytest.fixture
def user_client():
    return make_client("user@test.no")


@pytest.fixture
def friend_client():
    """Someone who is not in ALLOWED_EMAILS; gets apps only through a people list."""
    return make_client("venn@test.no")


@pytest.fixture
def make_page():
    """make_page(slug, level="all", people=(), title=None): a single-page app with that access level."""
    from app import access

    def _make(slug, level="all", people=(), title=None):
        main.save_page(slug, f"<!doctype html><html><head><title>{slug}</title></head><body>{slug}</body></html>",
                       create=True, private=False, title=title)
        path = main._meta_path(slug)
        meta = main._read_meta(path)
        access.set_level(meta, level, list(people))
        main._write_meta(path, meta)
    return _make


@pytest.fixture
def upload():
    def _upload(client, name, content, **form):
        data = content.encode() if isinstance(content, str) else content
        r = client.post("/api/upload", files={"file": (name, data)}, data=form)
        assert r.status_code == 200, r.text
        return r
    return _upload


# ---------------------------------------------------------------- oauth (Claude connector)
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PKCE_VERIFIER = "v" * 64
PKCE_CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(PKCE_VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def provider():
    from app import oauth
    return oauth.HubOAuthProvider()


@pytest.fixture
def oauth_client(provider):
    """A dynamically registered Claude client."""
    from mcp.shared.auth import OAuthClientInformationFull
    info = OAuthClientInformationFull(client_id="claude-test", client_name="Claude",
                                      redirect_uris=[CLAUDE_CALLBACK], token_endpoint_auth_method="none")
    asyncio.run(provider.register_client(info))
    return info


@pytest.fixture
def pending_req(provider, oauth_client):
    """id of an authorization request waiting for consent (state=xyz)."""
    from mcp.server.auth.provider import AuthorizationParams
    params = AuthorizationParams(state="xyz", scopes=None, code_challenge=PKCE_CHALLENGE,
                                 redirect_uri=CLAUDE_CALLBACK, redirect_uri_provided_explicitly=True,
                                 resource="https://hub.test/mcp")
    url = asyncio.run(provider.authorize(oauth_client, params))
    assert url.startswith("https://hub.test/oauth/consent?req=")
    return parse_qs(urlparse(url).query)["req"][0]


@pytest.fixture
def approved_code(admin_client, pending_req):
    """An authorization code that admin@test.no approved on the consent page."""
    r = admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"})
    assert r.status_code in (302, 303), r.text
    return parse_qs(urlparse(r.headers["location"]).query)["code"][0]


@pytest.fixture
def issued_token(provider, oauth_client, approved_code):
    """A valid access token string for admin@test.no."""
    code = asyncio.run(provider.load_authorization_code(oauth_client, approved_code))
    return asyncio.run(provider.exchange_authorization_code(oauth_client, code)).access_token
