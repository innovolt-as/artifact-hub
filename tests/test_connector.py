"""The MCP connector: JSON-RPC straight at /mcp, with a token from the OAuth provider."""
import json
from datetime import datetime

import pytest

from tests.conftest import make_client

PAGE = "<!doctype html><html><body><h1>Hei</h1></body></html>"


@pytest.fixture
def token(issued_token):
    return issued_token


@pytest.fixture
def mcp():
    """A client that runs the app's lifespan, so the MCP session manager is up."""
    with make_client() as c:
        yield c


def rpc(client, token, method, params=None, id=1):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
        headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"},
    )
    return r


def call(client, token, name, **arguments):
    r = rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def text(result) -> str:
    return "".join(c["text"] for c in result["content"] if c["type"] == "text")


def test_mcp_requires_token(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]


def test_metadata_endpoints(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["registration_endpoint"].startswith("https://hub.test")
    assert meta["authorization_endpoint"] == "https://hub.test/authorize"
    assert meta["token_endpoint"] == "https://hub.test/token"
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200 and r.json()["resource"] == "https://hub.test/mcp"


def test_lists_six_tools(mcp, token):
    r = rpc(mcp, token, "tools/list")
    assert r.status_code == 200, r.text
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(tools) == {"list_apps", "get_app", "create_app", "update_app", "edit_app", "update_app_info"}
    assert tools["list_apps"]["annotations"]["readOnlyHint"] is True
    assert tools["get_app"]["annotations"]["readOnlyHint"] is True
    assert tools["update_app"]["annotations"]["destructiveHint"] is True
    assert tools["edit_app"]["annotations"]["destructiveHint"] is True
    assert "list_apps" in tools["update_app"]["description"]
    assert "get_app" in tools["edit_app"]["description"]


def test_create_then_list_then_get(mcp, token, hub):
    res = call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei", emoji="👋")
    assert not res.get("isError"), res
    assert "https://hub.test/a/hei/" in text(res)
    assert hub._read_meta(hub.ARTIFACTS_DIR / "hei.meta.json")["admin_only"] is True  # private by default

    apps = json.loads(text(call(mcp, token, "list_apps")))
    hei = next(a for a in apps if a["slug"] == "hei")
    assert hei["title"] == "Hei" and hei["private"] is True and hei["editable"] is True
    assert datetime.fromisoformat(hei["updated"]).tzinfo is not None

    got = json.loads(text(call(mcp, token, "get_app", slug="hei")))
    assert got["html"] == PAGE and "hub.js" not in got["html"]
    assert (got["title"], got["emoji"], got["description"]) == ("Hei", "👋", "")


def test_create_existing_returns_error_text(mcp, token):
    call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    res = call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    assert res["isError"] is True
    assert "update_app" in text(res) and "finnes allerede" in text(res)


def test_update_missing_and_link_card_refused(mcp, token, hub):
    res = call(mcp, token, "update_app", slug="finnes-ikke", html=PAGE)
    assert res["isError"] is True and "Fant ingen" in text(res)
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text('{"url": "https://x.no", "title": "K"}')
    res = call(mcp, token, "update_app", slug="kort", html=PAGE)
    assert res["isError"] is True and "update_app_info" in text(res)


def test_update_app_replaces_and_keeps_private(mcp, token, hub):
    call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    res = call(mcp, token, "update_app", slug="hei", html=PAGE.replace("Hei", "Hallo"))
    assert not res.get("isError"), res
    assert "Hallo" in (hub.ARTIFACTS_DIR / "hei.html").read_text()
    assert hub._read_meta(hub.ARTIFACTS_DIR / "hei.meta.json")["admin_only"] is True


def test_edit_app_via_mcp(mcp, token, hub):
    call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    res = call(mcp, token, "edit_app", slug="hei", edits=[{"old": "<h1>Hei</h1>", "new": "<h1>Hallo</h1>"}])
    assert not res.get("isError"), res
    assert "<h1>Hallo</h1>" in (hub.ARTIFACTS_DIR / "hei.html").read_text()
    res = call(mcp, token, "edit_app", slug="hei", edits=[{"old": "finnes ikke", "new": "x"}])
    assert res["isError"] is True and "fant ikke teksten" in text(res)


def test_update_app_info_publishes(mcp, token, hub):
    call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    res = call(mcp, token, "update_app_info", slug="hei", private=False, description="Ny")
    assert not res.get("isError"), res
    meta = hub._read_meta(hub.ARTIFACTS_DIR / "hei.meta.json")
    assert "admin_only" not in meta and meta["description"] == "Ny"


def test_non_admin_token_refused(mcp, token, monkeypatch, hub):
    monkeypatch.setattr(hub, "ADMIN_EMAILS", set())
    r = rpc(mcp, token, "tools/list")
    assert r.status_code == 401


def test_existing_routes_still_work(admin_client):  # mounting on "/" must not shadow FastAPI
    assert admin_client.get("/admin").status_code == 200 and admin_client.get("/healthz").json() == {"ok": True}
    assert admin_client.get("/").status_code == 200


def test_folder_app_get_update_edit(mcp, token, hub):
    d = hub.ARTIFACTS_DIR / "mappe"
    d.mkdir()
    (d / "index.html").write_text(PAGE)
    (d / "sw.js").write_text("// sw")
    (d / "meta.json").write_text('{"title": "Mappe"}')
    listed = {a["slug"]: a for a in json.loads(text(call(mcp, token, "list_apps")))}
    assert listed["mappe"]["editable"] is True and listed["mappe"]["kind"] == "app"
    got = json.loads(text(call(mcp, token, "get_app", slug="mappe")))
    assert got["html"] == PAGE and got["kind"] == "app"
    res = call(mcp, token, "update_app", slug="mappe", html=PAGE.replace("Hei", "Hallo"))
    assert not res.get("isError"), res
    assert "Hallo" in (d / "index.html").read_text() and (d / "sw.js").read_text() == "// sw"
    res = call(mcp, token, "edit_app", slug="mappe", edits=[{"old": "Hallo", "new": "Hade"}])
    assert not res.get("isError"), res
    assert "Hade" in (d / "index.html").read_text()
    assert not (hub.ARTIFACTS_DIR / "mappe.html").exists()
