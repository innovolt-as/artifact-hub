"""The MCP connector: JSON-RPC straight at /mcp, with a token from the OAuth provider."""
import hashlib
import json
from datetime import datetime

import pytest

from app import i18n
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


def test_lists_all_tools(mcp, token):
    r = rpc(mcp, token, "tools/list")
    assert r.status_code == 200, r.text
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(tools) == {"list_apps", "get_app", "create_app", "update_app", "edit_app", "update_app_info",
                          "list_app_data", "get_app_data", "set_app_data", "delete_app_data"}
    assert tools["list_app_data"]["annotations"]["readOnlyHint"] is True
    assert tools["get_app_data"]["annotations"]["readOnlyHint"] is True
    assert tools["set_app_data"]["annotations"]["destructiveHint"] is True
    assert tools["list_apps"]["annotations"]["readOnlyHint"] is True
    assert tools["get_app"]["annotations"]["readOnlyHint"] is True
    assert tools["update_app"]["annotations"]["destructiveHint"] is True
    assert tools["edit_app"]["annotations"]["destructiveHint"] is True
    assert "list_apps" in tools["update_app"]["description"]
    assert "get_app" in tools["edit_app"]["description"]
    assert "shared_data" in tools["create_app"]["inputSchema"]["properties"]
    assert {"shared_data", "copy_my_data"} <= set(tools["update_app_info"]["inputSchema"]["properties"])


def test_create_then_list_then_get(mcp, token, hub):
    res = call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei", emoji="👋")
    assert not res.get("isError"), res
    assert "https://hub.test/a/hei/" in text(res)
    assert hub._read_meta(hub.ARTIFACTS_DIR / "hei.meta.json")["admin_only"] is True  # private by default

    apps = json.loads(text(call(mcp, token, "list_apps")))
    hei = next(a for a in apps if a["slug"] == "hei")
    assert hei["title"] == "Hei" and hei["access"] == "bare meg" and "private" not in hei and hei["editable"] is True
    assert datetime.fromisoformat(hei["updated"]).tzinfo is not None

    got = json.loads(text(call(mcp, token, "get_app", slug="hei")))
    assert got["html"] == PAGE and "hub.js" not in got["html"]
    assert (got["title"], got["emoji"], got["description"]) == ("Hei", "👋", "")


def test_get_app_shows_card_line_or_error(mcp, token, hub):
    page = "<!doctype html><html><head><title>T</title></head><body>{}</body></html>"
    ok = "<script data-hub-card>function hubCard() { return 'tre'; }</script>"
    bad = "<script data-hub-card>function hubCard() { throw new Error('au'); }</script>"
    for slug, body in (("ok", ok), ("bad", bad), ("none", "")):
        call(mcp, token, "create_app", slug=slug, html=page.format(body), title=slug)
    card = lambda slug: json.loads(text(call(mcp, token, "get_app", slug=slug)))["card"]  # noqa: E731
    assert card("ok") == {"text": "tre"}
    assert card("bad")["error"].startswith("failed")
    assert card("none") is None


def test_get_app_card_is_the_line_the_card_shows(mcp, token):  # trimmed, cut at 140, blank is no line
    page = "<!doctype html><html><head><title>T</title></head><body>{}</body></html>"
    recipes = {"blank": "'   '", "long": "'  ' + 'y'.repeat(200)", "padded": "'  tre \\n'"}
    for slug, value in recipes.items():
        call(mcp, token, "create_app", slug=slug, title=slug,
             html=page.format(f"<script data-hub-card>function hubCard() {{ return {value}; }}</script>"))
    card = lambda slug: json.loads(text(call(mcp, token, "get_app", slug=slug)))["card"]  # noqa: E731
    assert card("blank") == {"text": None}
    assert card("long") == {"text": "y" * 140}
    assert card("padded") == {"text": "tre"}


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


def _page(hub, slug="mat"):
    (hub.ARTIFACTS_DIR / f"{slug}.html").write_text(PAGE)
    (hub.ARTIFACTS_DIR / f"{slug}.meta.json").write_text("{}")


def test_app_data_roundtrip_reaches_the_app_store(mcp, token, hub):
    _page(hub)
    day = {"date": "2026-10-22", "items": [{"name": "Banan", "p": 1.4, "k": 108}]}
    res = call(mcp, token, "set_app_data", slug="mat", path="days/2026-10-22", data=day)
    assert not res.get("isError"), res
    got = json.loads(text(call(mcp, token, "get_app_data", slug="mat", path="days/2026-10-22")))
    assert got["exists"] is True and got["data"] == day
    assert json.loads(text(call(mcp, token, "list_app_data", slug="mat"))) == {"days": ["2026-10-22"]}
    assert json.loads(text(call(mcp, token, "list_app_data", slug="mat", collection="days"))) == {"2026-10-22": day}
    # the app itself (hub.js -> /api/store) sees the same document for the same user
    with make_client(_token_email(hub, token)) as app_client:
        r = app_client.get("/api/store/mat/d", params={"path": "days/2026-10-22"})
        assert r.status_code == 200 and r.json()["data"] == day


def _token_email(hub, token):
    """The e-mail the connector token belongs to."""
    with hub.db() as con:
        row = con.execute("SELECT email FROM oauth_tokens WHERE token_hash=?",
                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return row["email"] if row else "admin@test.no"


def test_app_data_is_private_per_user(mcp, token, hub, user_client):
    _page(hub)
    call(mcp, token, "set_app_data", slug="mat", path="days/2026-10-22", data={"items": [1]})
    r = user_client.get("/api/store/mat/d", params={"path": "days/2026-10-22"})
    assert r.status_code == 200 and r.json()["data"] is None
    user_client.put("/api/store/mat/d", params={"path": "days/2026-10-22"}, json={"items": ["annen"]})
    got = json.loads(text(call(mcp, token, "get_app_data", slug="mat", path="days/2026-10-22")))
    assert got["data"] == {"items": [1]}


def test_app_data_merge_and_delete(mcp, token, hub):
    _page(hub)
    call(mcp, token, "set_app_data", slug="mat", path="settings/main", data={"weight": 90, "favs": {"a": 1}})
    res = call(mcp, token, "set_app_data", slug="mat", path="settings/main", data={"favs": {"b": 2}}, merge=True)
    assert json.loads(text(res))["data"] == {"weight": 90, "favs": {"a": 1, "b": 2}}
    assert "Slettet" in text(call(mcp, token, "delete_app_data", slug="mat", path="settings/main"))
    assert json.loads(text(call(mcp, token, "get_app_data", slug="mat", path="settings/main")))["exists"] is False
    assert "Fant ikke" in text(call(mcp, token, "delete_app_data", slug="mat", path="settings/main"))


def test_app_data_refuses_bad_input(mcp, token, hub):
    _page(hub)
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text('{"url": "https://x.no", "title": "K"}')
    res = call(mcp, token, "set_app_data", slug="kort", path="days/x", data={})
    assert res["isError"] is True and "Lenkekort" in text(res)
    res = call(mcp, token, "set_app_data", slug="finnes-ikke", path="days/x", data={})
    assert res["isError"] is True
    res = call(mcp, token, "set_app_data", slug="mat", path="days", data={})
    assert res["isError"] is True and "partall" in text(res)
    res = call(mcp, token, "list_app_data", slug="mat", collection="days/x")
    assert res["isError"] is True and "oddetall" in text(res)
    res = call(mcp, token, "set_app_data", slug="mat", path="days/x", data={"s": "x" * 300_000})
    assert res["isError"] is True and "256 KB" in text(res)


def test_list_apps_shows_people_level(mcp, token, hub, make_page):
    make_page("p", "people", ["a@x.no", "b@x.no"])
    apps = json.loads(text(call(mcp, token, "list_apps")))
    assert next(a for a in apps if a["slug"] == "p")["access"] == "2 personer"


def test_create_app_with_shared_data(mcp, token, hub):
    res = call(mcp, token, "create_app", slug="radar", html=PAGE, title="Radar", shared_data=True)
    assert not res.get("isError"), res
    assert hub._read_meta(hub.ARTIFACTS_DIR / "radar.meta.json")["data"] == "shared"
    apps = json.loads(text(call(mcp, token, "list_apps")))
    assert next(a for a in apps if a["slug"] == "radar")["data"] == "shared"


def test_update_app_info_copies_only_when_asked(mcp, token, hub, user_client):
    _page(hub, "radar")
    call(mcp, token, "set_app_data", slug="radar", path="briefs/a", data={"n": 1})
    call(mcp, token, "update_app_info", slug="radar", shared_data=True)
    assert user_client.get("/api/store/radar/d", params={"path": "briefs/a"}).json()["data"] is None
    call(mcp, token, "update_app_info", slug="radar", shared_data=False)
    res = call(mcp, token, "update_app_info", slug="radar", shared_data=True, copy_my_data=True)
    assert not res.get("isError"), res
    assert user_client.get("/api/store/radar/d", params={"path": "briefs/a"}).json()["data"] == {"n": 1}


def test_shared_app_data_through_the_connector(mcp, token, hub, user_client):
    _page(hub, "radar")
    call(mcp, token, "update_app_info", slug="radar", shared_data=True)
    call(mcp, token, "set_app_data", slug="radar", path="briefs/a", data={"n": 1})
    call(mcp, token, "set_app_data", slug="radar", path="data/users/admin@test.no/p", data={"me": 1})
    assert json.loads(text(call(mcp, token, "list_app_data", slug="radar"))) == {
        "briefs": ["a"], "data/users/admin@test.no": ["p"]}
    assert user_client.get("/api/store/radar/d", params={"path": "briefs/a"}).json()["data"] == {"n": 1}


def test_instructions_explain_shared_data_and_ask_first():
    from app import connector
    assert "shared_data" in connector.INSTRUCTIONS and "data/users/" in connector.INSTRUCTIONS
    assert "ask" in connector.INSTRUCTIONS.lower()


def test_instructions_explain_rounds_errors_and_the_fixed_banner():
    from app import cards, connector
    text = connector.INSTRUCTIONS
    assert "Promise.all" in text and f"{cards.MAX_ROUNDS} rounds" in text and f"{cards.MAX_READS} paths" in text
    for code in (*cards.CODES, "too_many_reads", "bad_path", "failed: <message>"):
        assert code in text, code
    assert "top: var(--hub-banner-h, 0px)" in text


def test_connector_writes_are_recorded(mcp, token, hub):
    _page(hub)
    call(mcp, token, "set_app_data", slug="mat", path="days/d", data={})
    with hub.db() as con:
        row = con.execute("SELECT slug, email, at FROM claude_writes").fetchone()
    assert (row["slug"], row["email"]) == ("mat", "admin@test.no") and row["at"] > 0


def test_sharing_a_claude_filled_app_warns(mcp, token, hub):
    _page(hub)
    hub._write_meta(hub.ARTIFACTS_DIR / "mat.meta.json", {"admin_only": True})
    call(mcp, token, "set_app_data", slug="mat", path="days/d", data={})
    res = call(mcp, token, "update_app_info", slug="mat", private=False)
    assert "Claude fyller denne appen" in text(res)


def test_copy_my_data_says_when_shared_data_exists(mcp, token, hub):
    _page(hub, "radar")
    call(mcp, token, "update_app_info", slug="radar", shared_data=True)
    call(mcp, token, "set_app_data", slug="radar", path="briefs/a", data={"n": 1})  # a shared document
    call(mcp, token, "update_app_info", slug="radar", shared_data=False)
    res = call(mcp, token, "update_app_info", slug="radar", shared_data=True, copy_my_data=True)
    assert not res.get("isError"), res
    assert "fra før" in text(res) and "Kopierte" not in text(res)


# ---------------------------------------------------------------- public sharing and the agent zone
ME = "admin@test.no"
OTHER = "user@test.no"


def _shared_app(hub, mcp, token, slug="radar", **info):
    _page(hub, slug)
    res = call(mcp, token, "update_app_info", slug=slug, shared_data=True, **info)
    assert not res.get("isError"), res


def _guest_reply(hub, slug="radar", doc_id="r1"):
    """A reply a guest left in the connected user's guests/main zone (stored as the guest API stores it)."""
    from app import public
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                    (slug, ME, public.zone_collection(ME, "guests", "main"), doc_id,
                     json.dumps({"t": "secret wish", "_guest": "h"})))


def _app(mcp, token, slug="radar"):
    return next(a for a in json.loads(text(call(mcp, token, "list_apps"))) if a["slug"] == slug)


def test_update_app_info_sets_public_settings(mcp, token, hub):
    _page(hub, "radar")
    res = call(mcp, token, "update_app_info", slug="radar", shared_data=True, public_sharing=True,
               public_read=["products"], guests_hidden=True, agent_zone=True)
    assert not res.get("isError"), res
    meta = hub._read_meta(hub.ARTIFACTS_DIR / "radar.meta.json")
    assert (meta["public"], meta["public_read"], meta["guests_hidden"], meta["agent"]) == (
        True, ["products"], True, True)
    res = call(mcp, token, "update_app_info", slug="radar", public_sharing=False, public_read=[], agent_zone=False)
    assert not res.get("isError"), res
    meta = hub._read_meta(hub.ARTIFACTS_DIR / "radar.meta.json")
    assert "public" not in meta and "public_read" not in meta and "agent" not in meta


def test_public_settings_need_shared_data(mcp, token, hub):
    _page(hub, "radar")
    res = call(mcp, token, "update_app_info", slug="radar", public_sharing=True)
    assert res["isError"]
    assert "public" not in hub._read_meta(hub.ARTIFACTS_DIR / "radar.meta.json")


def test_create_app_with_public_settings(mcp, token, hub):
    res = call(mcp, token, "create_app", slug="radar", html=PAGE, title="Radar", shared_data=True,
               public_sharing=True, public_read=["products"], guests_hidden=True, agent_zone=True)
    assert not res.get("isError"), res
    app = _app(mcp, token)
    assert (app["public"], app["public_read"], app["guests_hidden"], app["agent"]) == (
        True, ["products"], True, True)


def test_list_apps_shows_public_settings(mcp, token, hub):
    _page(hub, "plain")
    plain = _app(mcp, token, "plain")
    assert (plain["public"], plain["public_read"], plain["guests_hidden"], plain["agent"]) == (
        False, [], False, False)
    _shared_app(hub, mcp, token, public_sharing=True, public_read=["products"], agent_zone=True)
    app = _app(mcp, token)
    assert (app["public"], app["public_read"], app["guests_hidden"], app["agent"]) == (True, ["products"], False, True)
    got = json.loads(text(call(mcp, token, "get_app", slug="radar")))
    assert (got["public"], got["public_read"], got["guests_hidden"], got["agent"]) == (
        True, ["products"], False, True)


def test_connector_cannot_unhide_guest_replies(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True, guests_hidden=True)
    _guest_reply(hub)
    res = call(mcp, token, "update_app_info", slug="radar", guests_hidden=False)
    assert res["isError"]
    assert _app(mcp, token)["guests_hidden"] is True


def test_connector_never_returns_hidden_guest_zone(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True, guests_hidden=True)
    _guest_reply(hub)
    zone = f"data/users/{ME}/guests/main"
    overview = text(call(mcp, token, "list_app_data", slug="radar"))
    assert "guests" not in overview and "r1" not in overview
    listing = text(call(mcp, token, "list_app_data", slug="radar", collection=zone))
    assert json.loads(listing) == {} and "secret wish" not in listing
    got = json.loads(text(call(mcp, token, "get_app_data", slug="radar", path=f"{zone}/r1")))
    assert got["exists"] is False and got["data"] is None
    # visible once the replies are not hidden, and never with the _guest stamp
    call(mcp, token, "update_app_info", slug="radar", guests_hidden=False)  # refused while replies exist
    assert "secret wish" not in text(call(mcp, token, "list_app_data", slug="radar", collection=zone))


def test_visible_guest_zone_hides_only_the_stamp(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True)
    _guest_reply(hub)
    zone = f"data/users/{ME}/guests/main"
    got = json.loads(text(call(mcp, token, "get_app_data", slug="radar", path=f"{zone}/r1")))
    assert got["data"] == {"t": "secret wish"}


def test_connector_reads_and_writes_other_users_agent_zone(mcp, token, hub):
    _shared_app(hub, mcp, token, agent_zone=True)
    path = f"data/users/{OTHER}/agent/briefs/today"
    res = call(mcp, token, "set_app_data", slug="radar", path=path, data={"n": 1})
    assert not res.get("isError"), res
    assert json.loads(text(call(mcp, token, "get_app_data", slug="radar", path=path)))["data"] == {"n": 1}
    res = call(mcp, token, "delete_app_data", slug="radar", path=path)
    assert text(res) == i18n.t("mcp.deleted", path=path)
    # outside the agent zone another user's branch stays closed
    res = call(mcp, token, "set_app_data", slug="radar", path=f"data/users/{OTHER}/private/x", data={})
    assert res["isError"]


def test_agent_zone_closed_without_the_setting(mcp, token, hub):
    _shared_app(hub, mcp, token)
    res = call(mcp, token, "set_app_data", slug="radar", path=f"data/users/{OTHER}/agent/x/y", data={})
    assert res["isError"]


def test_overview_lists_agent_zones_of_all_users(mcp, token, hub):
    _shared_app(hub, mcp, token, agent_zone=True)
    for who in (OTHER, "third@test.no"):
        call(mcp, token, "set_app_data", slug="radar", path=f"data/users/{who}/agent/briefs/a", data={"n": 1})
    overview = json.loads(text(call(mcp, token, "list_app_data", slug="radar")))
    assert overview[f"data/users/{OTHER}/agent/briefs"] == ["a"]
    assert overview["data/users/third@test.no/agent/briefs"] == ["a"]


def test_delete_in_own_guest_zone_does_not_claim_a_deletion(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True, guests_hidden=True)
    _guest_reply(hub)
    res = call(mcp, token, "delete_app_data", slug="radar", path=f"data/users/{ME}/guests/main/r1")
    path = f"data/users/{ME}/guests/main/r1"
    assert not res.get("isError") and text(res) == i18n.t("mcp.guest_zone_deleted", path=path)
    assert text(res) != i18n.t("mcp.deleted", path=path)


def test_create_app_partly_refused_says_the_app_exists(mcp, token, hub):
    res = call(mcp, token, "create_app", slug="radar", html=PAGE, title="Radar", shared_data=True,
               public_sharing=True, public_read=["bad name"])
    assert res["isError"]
    assert (hub.ARTIFACTS_DIR / "radar.html").exists()
    assert text(res).startswith(i18n.t("mcp.created_but", url="https://hub.test/a/radar/", reason="")[:30])
    assert "bad name" in text(res)
    # the reason comes last, so the reply reads the same whether or not it ends in a period
    reason = i18n.t("err.public_read_bad", name="bad name")
    assert text(res) == i18n.t("mcp.created_but", url="https://hub.test/a/radar/", reason=reason)
    for lang in ("nb", "en"):
        assert i18n._load(lang)["mcp.created_but"].endswith(": {reason}"), lang


def test_update_app_info_partly_refused_lists_what_went_through(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True, guests_hidden=True)
    _guest_reply(hub)
    res = call(mcp, token, "update_app_info", slug="radar", title="New title", guests_hidden=False)
    assert res["isError"]
    assert i18n.t("mcp.info_updated", slug="radar") in text(res)
    assert _app(mcp, token)["title"] == "New title" and _app(mcp, token)["guests_hidden"] is True


def test_update_app_info_refused_first_step_says_no_progress(mcp, token, hub):
    res = call(mcp, token, "update_app_info", slug="missing", title="x")
    assert res["isError"] and i18n.t("mcp.info_updated", slug="missing") not in text(res)


def test_delete_guest_zone_path_is_normalized(mcp, token, hub):
    _shared_app(hub, mcp, token, public_sharing=True, guests_hidden=True)
    _guest_reply(hub)
    for path in (f"/data/users/{ME}/guests/main/r1", f"data//users/{ME}/guests/main//r1"):
        res = call(mcp, token, "delete_app_data", slug="radar", path=path)
        assert text(res) == i18n.t("mcp.guest_zone_deleted", path=path), path


def test_instructions_mention_public_sharing():
    from app import connector
    t = connector.INSTRUCTIONS
    for needle in ("public_sharing", "data/users/<e-mail>/public/<name>/", "data/users/<e-mail>/guests/<name>/",
                   "data/users/<e-mail>/agent/", 'window.claude.use("share")', "share.scope(name, title)", "by id", "share sheet",
                   "{ db, today, now, timeZone, user }"):
        assert needle in t, needle
    assert "sensitive" in t and "hidden" in t
    assert "hubCard({{" not in t and "{ db, today, now, timeZone }" not in t


# ---------------------------------------------------------------- final review
@pytest.mark.parametrize("settings", [{}, {"agent_zone": True}])
def test_delete_in_guests_path_is_plain_where_no_guest_zone_applies(mcp, token, hub, settings):
    _shared_app(hub, mcp, token, **settings)
    _guest_reply(hub)
    path = f"data/users/{ME}/guests/main/r1"
    assert text(call(mcp, token, "delete_app_data", slug="radar", path=path)) == i18n.t("mcp.deleted", path=path)
    assert text(call(mcp, token, "delete_app_data", slug="radar", path=path)) == i18n.t("mcp.not_deleted", path=path)
    _page(hub, "mat")  # personal data
    path = f"data/users/{ME}/guests/main/x"
    assert text(call(mcp, token, "delete_app_data", slug="mat", path=path)) == i18n.t("mcp.not_deleted", path=path)


@pytest.mark.parametrize("settings", [{"public_sharing": True}, {"guests_hidden": True}])
def test_delete_in_guest_zone_is_handled_wherever_the_rules_apply(mcp, token, hub, settings):
    _shared_app(hub, mcp, token, **settings)
    path = f"data/users/{ME}/guests/main/r1"
    assert text(call(mcp, token, "delete_app_data", slug="radar", path=path)) == i18n.t("mcp.guest_zone_deleted", path=path)
    path = f"data/users/{ME}/guests"  # the document guests itself is not in the zone
    assert text(call(mcp, token, "delete_app_data", slug="radar", path=path)) == i18n.t("mcp.not_deleted", path=path)


def test_set_app_data_refuses_values_json_cannot_send_back(mcp, token, hub):
    _page(hub, "mat")
    for value in ("NaN", "Infinity", "-Infinity"):  # a lone surrogate is refused before the tool, as a parse error
        body = ('{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "set_app_data", "arguments": '
                '{"slug": "mat", "path": "days/d1", "data": {"t": ' + value + '}}}}')
        r = mcp.post("/mcp", content=body, headers={"Accept": "application/json, text/event-stream",
                                                    "Authorization": f"Bearer {token}",
                                                    "content-type": "application/json"})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["isError"] and text(res) == i18n.t("store.bad_json"), value
    assert hub.doc_get("mat", ME, "days/d1") is None
