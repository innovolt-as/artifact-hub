"""Messages to the apps (hub.js), to Claude (connector), the consent page and the password CLI."""
import html
import io
import json
import re

from app import i18n, passwd
from tests.test_connector import PAGE, call, mcp, rpc, text, token  # noqa: F401  (fixtures)
from tests.textutil import _NORWEGIAN, assert_no_norwegian

PAGE_SRC = "<!doctype html><html><head><title>p</title></head><body>hi</body></html>"


def _no_norwegian_text(s: str) -> None:
    assert not _NORWEGIAN.search(s), f"Norwegian text left: {s!r}"


def _strings_block(body: str) -> dict:
    m = re.search(r'<script src="/static/hub.js"[^>]* data-strings="([^"]*)"', body)
    assert m, "no data-strings on the hub.js tag"
    return json.loads(html.unescape(m.group(1)))


def test_hub_strings_on_app_pages_are_script_safe(admin_client, make_page, monkeypatch):
    make_page("p")
    monkeypatch.setattr(i18n, "js", lambda prefix: {"x": "</script><b>"})
    body = admin_client.get("/a/p/").text
    assert "</script><b>" not in body
    assert _strings_block(body) == {"x": "</script><b>"}
    assert 'id="__hub_strings"' not in body


def test_hub_js_strings_nb(admin_client, make_page):
    make_page("p")
    body = admin_client.get("/a/p/").text
    s = _strings_block(body)
    assert s["not_logged_in"] == "Ikke innlogget"
    assert s["network"] == "Nettverksfeil"
    assert s["save_args"] == "filename og data må være satt"
    assert "src=\"/static/hub.js\"" in body


def test_hub_js_strings_en(admin_client, make_page, english):
    make_page("p")
    s = _strings_block(admin_client.get("/a/p/").text)
    assert s["network"] == "Network error"
    for v in s.values():
        _no_norwegian_text(v)


def test_hub_js_reads_block_and_falls_back_to_key():
    src = open("app/static/hub.js", encoding="utf-8").read()
    assert "dataset.strings" in src and "__hub_strings" not in src
    assert not re.search(r"Nettverksfeil|Ikke innlogget|må være satt|Ugyldig|Ukjent|Feil \$", src)


def test_connector_messages_en(mcp, token, english, hub):
    res = call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    assert text(res).startswith("Created private app: ")
    res = call(mcp, token, "create_app", slug="hei", html=PAGE, title="Hei")
    assert res["isError"] is True and "already" in text(res)
    _no_norwegian_text(text(res))
    res = call(mcp, token, "edit_app", slug="hei", edits=[])
    assert text(res) == "No changes given."
    res = call(mcp, token, "edit_app", slug="hei", edits=[{"old": "zzz", "new": "y"}])
    _no_norwegian_text(text(res))
    assert "Nothing has changed" in text(res)
    res = call(mcp, token, "edit_app", slug="hei", edits=[{"old": "Hei", "new": "Yo"}])
    assert text(res) == "Edited (1 edit): https://hub.test/a/hei/"
    assert text(call(mcp, token, "update_app", slug="hei", html=PAGE)) == "Updated: https://hub.test/a/hei/"
    assert text(call(mcp, token, "update_app_info", slug="hei", title="X")) == 'Updated info for "hei".'
    for slug_call in (call(mcp, token, "update_app", slug="nope", html=PAGE),
                      call(mcp, token, "update_app", slug="hei", html="just text"),
                      call(mcp, token, "create_app", slug="Bad Slug", html=PAGE, title="x"),
                      call(mcp, token, "get_app_data", slug="nope", path="a/b"),
                      call(mcp, token, "get_app_data", slug="hei", path="a"),
                      call(mcp, token, "list_app_data", slug="hei", collection="a/b"),
                      call(mcp, token, "set_app_data", slug="hei", path="a/b", data={"x": "y" * 300000})):
        assert slug_call["isError"] is True
        _no_norwegian_text(text(slug_call))
    assert text(call(mcp, token, "delete_app_data", slug="hei", path="a/b")) == "Could not find a/b; nothing deleted."
    call(mcp, token, "set_app_data", slug="hei", path="a/b", data={"x": 1})
    assert text(call(mcp, token, "delete_app_data", slug="hei", path="a/b")) == "Deleted a/b."


def test_connector_not_admin_en(english, hub, monkeypatch):
    from app import connector
    monkeypatch.setattr(connector, "get_access_token", lambda: None)
    try:
        connector._user()
    except hub.HubError as e:
        assert str(e) == "Only administrators can use this connection."
    else:
        raise AssertionError


def test_list_apps_description_has_no_norwegian(mcp, token):
    tools = {t["name"]: t for t in rpc(mcp, token, "tools/list").json()["result"]["tools"]}
    d = tools["list_apps"]["description"]
    for word in ("'alle'", "'bare meg'", "personer"):
        assert word not in d
    assert "language" in d
    _no_norwegian_text(d)


def test_instructions_example_is_english():
    from app import connector
    assert "93 hits" in connector.INSTRUCTIONS and "treff" not in connector.INSTRUCTIONS


def test_consent_en(admin_client, user_client, english, pending_req):
    body = admin_client.get(f"/oauth/consent?req={pending_req}").text
    assert_no_norwegian(body)
    assert "Allow" in body or "Give" in body
    assert "<title>Connect to Claude" in body
    body = admin_client.get("/oauth/consent?req=nope").text
    assert_no_norwegian(body)
    assert "invalid or has expired" in body
    body = user_client.get(f"/oauth/consent?req={pending_req}").text
    assert_no_norwegian(body)
    assert "Only administrators" in body


def test_consent_escapes_client_name(admin_client, pending_req, provider):
    from app import main
    with main.db() as con:
        row = con.execute("SELECT info FROM oauth_clients").fetchone()
        info = json.loads(row["info"])
        info["client_name"] = "<b>x</b>"
        con.execute("UPDATE oauth_clients SET info=?", (json.dumps(info),))
    body = admin_client.get(f"/oauth/consent?req={pending_req}").text
    assert "<b>x</b>" not in body and "&lt;b&gt;x&lt;/b&gt;" in body


def test_oauth_messages_en(english):
    import asyncio

    from mcp.server.auth.provider import RegistrationError
    from mcp.shared.auth import OAuthClientInformationFull

    from app import oauth
    info = OAuthClientInformationFull(client_id="evil", redirect_uris=["https://evil.example/cb"],
                                      token_endpoint_auth_method="none")
    try:
        asyncio.run(oauth.HubOAuthProvider().register_client(info))
    except RegistrationError as e:
        assert e.error_description.startswith("Only Claude")
    else:
        raise AssertionError


def test_passwd_cli_en(english, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("longenough1\nsomethingelse\n"))
    assert passwd.main(["set", "x@test.no"]) == 2
    err = capsys.readouterr().err
    assert "Passwords do not match" in err
    monkeypatch.setattr("sys.stdin", io.StringIO("short\nshort\n"))
    assert passwd.main(["set", "x@test.no"]) == 2
    assert "at least 10 characters" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("longenough1\nlongenough1\n"))
    assert passwd.main(["set", "x@test.no", "--temporary"]) == 0
    cap = capsys.readouterr()
    assert "Password set for x@test.no (must be changed at first login)" in cap.out
    _no_norwegian_text(cap.out + cap.err)
    assert passwd.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "x@test.no  must be changed  " in out
    _no_norwegian_text(out)


def test_passwd_cli_nb(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("a\nb\n"))
    assert passwd.main(["set", "x@test.no"]) == 2
    assert "Passordene er ulike" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("longenough1\nlongenough1\n"))
    assert passwd.main(["set", "x@test.no"]) == 0
    assert "Passord satt for x@test.no" in capsys.readouterr().out
    assert passwd.main(["list"]) == 0
    assert "x@test.no  satt  " in capsys.readouterr().out


def test_doc_api_error_en(user_client, make_page, english):
    make_page("p")
    r = user_client.put("/api/store/p/d?path=a/b", content="{nope")
    assert r.status_code == 400 and r.json()["detail"] == "Invalid JSON"
    r = user_client.put("/api/store/p/d?path=a/b", content="[1]")
    assert r.json()["detail"] == "A document must be a JSON object"
    r = user_client.put("/api/store/p/d?path=a/b&merge=1", content="{}")
    assert r.status_code == 404 and "not exist" in r.json()["detail"]
    r = user_client.put("/api/store/p/d?path=a/b", content="{\"x\":\"" + "y" * 300000 + "\"}")
    assert r.status_code == 413 and "256 KB" in r.json()["detail"]
    r = user_client.get("/api/store/p/d?path=a")
    assert r.status_code == 400
    _no_norwegian_text(r.json()["detail"])


def test_doc_api_error_nb(user_client, make_page):
    make_page("p")
    assert user_client.put("/api/store/p/d?path=a/b", content="{nope").json()["detail"] == "Ugyldig JSON"
    assert user_client.get("/api/store/p/d?path=a").json()["detail"] == "Ugyldig sti: a"


def test_app_data_api_errors_en(hub, user_client, english):
    r = user_client.get("/api/data/Bad Name/x")
    assert r.status_code == 400 and r.json()["detail"] == "Invalid app name"
    r = user_client.get("/api/data/app/x")
    assert r.status_code == 404 and r.json()["detail"] == "Not found"
    r = user_client.put("/api/data/app/x", content="{}", headers={"content-type": "text/plain"})
    assert r.status_code == 415 and "application/json" in r.json()["detail"]
    r = user_client.post("/api/data/app/_batch", json={"set": 1})
    assert r.json()["detail"] == "Invalid batch"
    r = user_client.put("/api/data/app/x", json={"value": "v" * (hub.MAX_VALUE_BYTES + 1)})
    assert r.status_code == 413 and r.json()["detail"] == "The value is too large"
    r = user_client.post("/api/prefs/view", json={"view": "zzz"})
    assert r.status_code == 400 and r.json()["detail"] == "Unknown view: zzz"


def test_api_not_logged_in_en(client, english):
    assert client.get("/api/me").json()["detail"] == "Not logged in"


def test_hub_error_doc_not_norwegian():
    from app import main
    assert "Norwegian" not in (main.HubError.__doc__ or "")
