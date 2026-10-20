"""The whole connector flow over HTTP through the real SDK routes, so an `mcp` upgrade that breaks the chain fails here."""
from urllib.parse import parse_qs, urlparse

from tests.conftest import CLAUDE_CALLBACK, PKCE_CHALLENGE, PKCE_VERIFIER, make_client

RESOURCE = "https://hub.test/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _rpc(method, id=1, params=None):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def _connect(c):
    """register -> authorize -> consent -> token; returns (client info, token response)."""
    reg = c.post("/register", json={
        "client_name": "Claude", "redirect_uris": [CLAUDE_CALLBACK],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post"})
    assert reg.status_code == 201, reg.text
    ci = reg.json()
    r = c.get("/authorize", params={
        "response_type": "code", "client_id": ci["client_id"], "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": PKCE_CHALLENGE, "code_challenge_method": "S256", "state": "st", "resource": RESOURCE})
    assert r.status_code == 302
    consent = urlparse(r.headers["location"])
    assert consent.path == "/oauth/consent"
    req = parse_qs(consent.query)["req"][0]
    return ci, req


def test_full_flow_register_to_tools_and_refresh():
    from app import main
    with make_client() as c:
        ci, req = _connect(c)
        c.cookies.set(main.COOKIE, main.signer.dumps({"email": "admin@test.no"}))
        r = c.post("/oauth/consent", data={"req": req, "decision": "allow"})
        assert r.status_code in (302, 303), r.text
        back = urlparse(r.headers["location"])
        assert f"{back.scheme}://{back.netloc}{back.path}" == CLAUDE_CALLBACK
        q = parse_qs(back.query)
        assert q["state"] == ["st"]
        c.cookies.clear()

        creds = {"client_id": ci["client_id"], "client_secret": ci["client_secret"]}
        tok = c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                     "redirect_uri": CLAUDE_CALLBACK, "code_verifier": PKCE_VERIFIER,
                                     "resource": RESOURCE, **creds})
        assert tok.status_code == 200, tok.text
        tk = tok.json()
        auth = {**MCP_HEADERS, "Authorization": f"Bearer {tk['access_token']}"}

        init = c.post("/mcp", headers=auth, json=_rpc("initialize", params={
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}))
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == main.SITE_NAME
        tools = c.post("/mcp", headers=auth, json=_rpc("tools/list", id=2))
        assert tools.status_code == 200, tools.text
        assert {t["name"] for t in tools.json()["result"]["tools"]} >= {"list_apps", "get_app", "create_app"}

        # a wrong Host must not reach the connector (DNS rebinding protection)
        bad = c.post("/mcp", headers={**auth, "Host": "127.0.0.1:8000"}, json=_rpc("tools/list", id=3))
        assert bad.status_code == 421

        rf = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tk["refresh_token"], **creds})
        assert rf.status_code == 200, rf.text
        again = c.post("/mcp", headers={**MCP_HEADERS, "Authorization": f"Bearer {rf.json()['access_token']}"},
                       json=_rpc("tools/list", id=4))
        assert again.status_code == 200
