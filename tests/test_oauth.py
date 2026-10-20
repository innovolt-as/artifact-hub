"""OAuth authorization server for the Claude connector: only admins may ever get tokens."""
import time
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams, RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull

from app import oauth
from tests.conftest import CLAUDE_CALLBACK, PKCE_CHALLENGE

def _client(*uris, client_id="c1"):
    return OAuthClientInformationFull(client_id=client_id, client_name="Claude", redirect_uris=list(uris))


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ---------------------------------------------------------------- registration
@pytest.mark.anyio
async def test_register_rejects_foreign_redirect(provider):
    with pytest.raises(RegistrationError) as e:
        await provider.register_client(_client("https://evil.example/cb"))
    assert e.value.error == "invalid_redirect_uri"
    assert await provider.get_client("c1") is None


@pytest.mark.anyio
async def test_register_rejects_mixed_redirects(provider):
    with pytest.raises(RegistrationError):
        await provider.register_client(_client(CLAUDE_CALLBACK, "https://claude.ai/api/mcp/auth_callback/x"))


@pytest.mark.anyio
async def test_register_rejects_missing_redirects(provider):
    with pytest.raises(RegistrationError):
        await provider.register_client(OAuthClientInformationFull(client_id="c1"))


@pytest.mark.anyio
async def test_register_accepts_claude_callback(provider):
    await provider.register_client(_client(CLAUDE_CALLBACK, "https://claude.com/api/mcp/auth_callback"))
    got = await provider.get_client("c1")
    assert got.client_name == "Claude"
    assert [str(u) for u in got.redirect_uris] == sorted(oauth.REDIRECT_ALLOWLIST)


@pytest.mark.anyio
async def test_authorize_returns_consent_url(provider, oauth_client, hub):
    params = AuthorizationParams(state="s", scopes=None, code_challenge=PKCE_CHALLENGE,
                                 redirect_uri=CLAUDE_CALLBACK, redirect_uri_provided_explicitly=True)
    url = await provider.authorize(oauth_client, params)
    assert url.startswith(f"{hub.BASE_URL}/oauth/consent?req=")
    assert len(_query(url)["req"]) >= 32


# ---------------------------------------------------------------- consent page
def test_consent_requires_login(client, pending_req):
    r = client.get(f"/oauth/consent?req={pending_req}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?next=")
    assert pending_req in r.headers["location"]


def test_consent_page_shows_client_and_question(admin_client, pending_req):
    r = admin_client.get(f"/oauth/consent?req={pending_req}")
    assert r.status_code == 200
    assert "Gi Claude tilgang til å publisere apper i" in r.text
    assert "Gi tilgang" in r.text and "Avbryt" in r.text and "Claude" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_consent_refuses_non_admin(user_client, pending_req, hub):
    r = user_client.get(f"/oauth/consent?req={pending_req}")
    assert r.status_code == 403
    r = user_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"})
    assert r.status_code == 403 and "location" not in r.headers
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0] == 0


def test_post_requires_login(client, pending_req, hub):
    r = client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"})
    assert r.status_code == 302 and r.headers["location"].startswith("/login?next=")
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0] == 0


def test_allow_redirects_with_code_and_state(admin_client, pending_req):
    r = admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"}, follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("https://claude.ai/api/mcp/auth_callback?") and "code=" in loc and "state=xyz" in loc


def test_deny_redirects_with_access_denied(admin_client, pending_req, hub):
    r = admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "deny"})
    q = _query(r.headers["location"])
    assert r.headers["location"].startswith(CLAUDE_CALLBACK)
    assert q["error"] == "access_denied" and q["state"] == "xyz" and "code" not in q
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0] == 0


def test_request_is_single_use(admin_client, pending_req):
    assert admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"}).status_code == 303
    r = admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"})
    assert r.status_code == 400 and "location" not in r.headers
    assert admin_client.get(f"/oauth/consent?req={pending_req}").status_code == 400


def test_request_expires(admin_client, pending_req, hub):
    with hub.db() as con:
        con.execute("UPDATE oauth_requests SET expires_at=?", (int(time.time()) - 1,))
    assert admin_client.get(f"/oauth/consent?req={pending_req}").status_code == 400
    r = admin_client.post("/oauth/consent", data={"req": pending_req, "decision": "allow"})
    assert r.status_code == 400 and "location" not in r.headers


def test_unknown_request(admin_client):
    assert admin_client.get("/oauth/consent?req=finnes-ikke").status_code == 400


# ---------------------------------------------------------------- tokens
@pytest.mark.anyio
async def test_code_carries_pkce_and_redirect(provider, oauth_client, approved_code):
    code = await provider.load_authorization_code(oauth_client, approved_code)
    assert code.code_challenge == PKCE_CHALLENGE
    assert str(code.redirect_uri) == CLAUDE_CALLBACK and code.redirect_uri_provided_explicitly
    assert code.resource == "https://hub.test/mcp" and code.subject == "admin@test.no"
    assert code.expires_at <= time.time() + 5 * 60


@pytest.mark.anyio
async def test_code_is_stored_hashed(provider, approved_code, hub):
    with hub.db() as con:
        rows = [r[0] for r in con.execute("SELECT code_hash FROM oauth_codes")]
    assert approved_code not in rows and len(rows) == 1


@pytest.mark.anyio
async def test_code_bound_to_client(provider, approved_code):
    other = _client(CLAUDE_CALLBACK, client_id="other")
    await provider.register_client(other)
    assert await provider.load_authorization_code(other, approved_code) is None


@pytest.mark.anyio
async def test_code_exchange_and_refresh(provider, oauth_client, approved_code, hub):
    code = await provider.load_authorization_code(oauth_client, approved_code)
    tok = await provider.exchange_authorization_code(oauth_client, code)
    assert tok.access_token and tok.refresh_token and tok.expires_in == 3600
    access = await provider.load_access_token(tok.access_token)
    assert access.subject == "admin@test.no" and access.client_id == oauth_client.client_id
    assert access.resource == "https://hub.test/mcp"
    assert access.expires_at <= time.time() + 3600

    with hub.db() as con:
        hashes = {r[0] for r in con.execute("SELECT token_hash FROM oauth_tokens")}
    assert tok.access_token not in hashes and tok.refresh_token not in hashes

    rt = await provider.load_refresh_token(oauth_client, tok.refresh_token)
    assert rt.subject == "admin@test.no" and rt.expires_at > time.time() + 89 * 24 * 3600
    tok2 = await provider.exchange_refresh_token(oauth_client, rt, rt.scopes)
    assert tok2.access_token != tok.access_token and tok2.refresh_token != tok.refresh_token
    assert await provider.load_access_token(tok2.access_token) is not None
    # old refresh token is spent
    assert await provider.load_refresh_token(oauth_client, tok.refresh_token) is None
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(oauth_client, rt, rt.scopes)


@pytest.mark.anyio
async def test_refresh_bound_to_client(provider, oauth_client, approved_code):
    tok = await provider.exchange_authorization_code(
        oauth_client, await provider.load_authorization_code(oauth_client, approved_code))
    other = _client(CLAUDE_CALLBACK, client_id="other")
    await provider.register_client(other)
    assert await provider.load_refresh_token(other, tok.refresh_token) is None
    assert await provider.load_refresh_token(oauth_client, tok.refresh_token) is not None


@pytest.mark.anyio
async def test_code_single_use_and_expires(provider, oauth_client, approved_code, hub):
    code = await provider.load_authorization_code(oauth_client, approved_code)
    await provider.exchange_authorization_code(oauth_client, code)
    assert await provider.load_authorization_code(oauth_client, approved_code) is None
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(oauth_client, code)

    params = AuthorizationParams(state=None, scopes=None, code_challenge=PKCE_CHALLENGE,
                                 redirect_uri=CLAUDE_CALLBACK, redirect_uri_provided_explicitly=True)
    req = _query(await provider.authorize(oauth_client, params))["req"]
    code2 = oauth._approve(req, "admin@test.no")
    with hub.db() as con:
        con.execute("UPDATE oauth_codes SET expires_at=?", (time.time() - 1,))
    assert await provider.load_authorization_code(oauth_client, code2) is None


@pytest.mark.anyio
async def test_access_token_expires(provider, issued_token, hub):
    with hub.db() as con:
        con.execute("UPDATE oauth_tokens SET expires_at=? WHERE kind='access'", (int(time.time()) - 1,))
    assert await provider.load_access_token(issued_token) is None


@pytest.mark.anyio
async def test_access_token_rejected_after_admin_removed(provider, issued_token, monkeypatch, hub):
    assert await provider.load_access_token(issued_token) is not None
    monkeypatch.setattr(hub, "ADMIN_EMAILS", set())
    assert await provider.load_access_token(issued_token) is None


@pytest.mark.anyio
async def test_no_tokens_for_code_of_removed_admin(provider, oauth_client, approved_code, monkeypatch, hub):
    code = await provider.load_authorization_code(oauth_client, approved_code)
    monkeypatch.setattr(hub, "ADMIN_EMAILS", set())
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(oauth_client, code)


@pytest.mark.anyio
async def test_revoke_removes_access_and_refresh(provider, oauth_client, issued_token, hub):
    access = await provider.load_access_token(issued_token)
    await provider.revoke_token(access)
    assert await provider.load_access_token(issued_token) is None
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_tokens").fetchone()[0] == 0



@pytest.mark.anyio
async def test_issuing_tokens_purges_expired_rows(provider, oauth_client, issued_token, hub):
    with hub.db() as con:
        con.execute("UPDATE oauth_tokens SET expires_at=?", (int(time.time()) - 1,))
    with hub.db() as con:
        oauth._issue(con, oauth_client.client_id, "admin@test.no", [], None)
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_tokens WHERE expires_at < ?",
                           (int(time.time()),)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM oauth_tokens").fetchone()[0] == 2


def test_consent_page_warns(admin_client, pending_req):
    r = admin_client.get(f"/oauth/consent?req={pending_req}")
    assert "Godkjenn bare hvis du nettopp startet tilkoblingen selv fra Claude." in r.text
