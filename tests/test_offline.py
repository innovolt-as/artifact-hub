import io
import zipfile

from tests.test_connector import PAGE, call, mcp, text, token  # noqa: F401  (fixtures)


def meta(hub, slug="a"):
    return hub._read_meta(hub._meta_path(slug))


def test_toggle_offline_on_and_off(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    assert admin_client.post("/api/toggle-offline", data={"slug": "a"}).json() == {"ok": True, "offline": True}
    assert meta(hub)["offline"] is True
    assert admin_client.post("/api/toggle-offline", data={"slug": "a"}).json() == {"ok": True, "offline": False}
    assert "offline" not in meta(hub)


def test_offline_survives_replace(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    admin_client.post("/api/toggle-offline", data={"slug": "a"})
    upload(admin_client, "a.html", "<body>y</body>")
    assert meta(hub)["offline"] is True


def test_offline_link_card_refused(hub, admin_client):
    admin_client.post("/api/link", data={"title": "L", "url": "https://example.com"})
    before = (hub.ARTIFACTS_DIR / "l.link.json").read_text()
    assert admin_client.post("/api/toggle-offline", data={"slug": "l"}).status_code == 404
    assert (hub.ARTIFACTS_DIR / "l.link.json").read_text() == before
    assert admin_client.post("/api/toggle-offline", data={"slug": "nope"}).status_code == 404


def test_offline_needs_admin(admin_client, user_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    banner = user_client.post("/api/toggle-banner", data={"slug": "a"}).status_code
    assert banner in (401, 403)
    assert user_client.post("/api/toggle-offline", data={"slug": "a"}).status_code == banner


def _folder():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", "<body>f</body>")
    return buf.getvalue()


def test_list_artifacts_offline_flag(hub, admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    upload(admin_client, "b.html", "<body>x</body>")
    upload(admin_client, "f.zip", _folder())
    admin_client.post("/api/link", data={"title": "L", "url": "https://example.com"})
    for slug in ("a", "f"):
        admin_client.post("/api/toggle-offline", data={"slug": slug})
    got = {a["slug"]: a["offline"] for a in hub.list_artifacts("admin@test.no")}
    assert got == {"a": True, "f": True, "b": False, "l": False}


def test_admin_row_and_switch(admin_client, upload):
    upload(admin_client, "a.html", "<body>x</body>")
    upload(admin_client, "b.html", "<body>x</body>")
    admin_client.post("/api/toggle-offline", data={"slug": "a"})
    page = admin_client.get("/admin").text
    assert page.count('data-offline="1"') == 1 and page.count('data-offline="0"') == 1
    assert page.count("virker uten nett") == 1
    assert page.count('id="asOffline"') == 1 and 'id="asOffline"' in page and 'role="switch" id="asOffline"' in page


def test_connector_update_app_info_offline(mcp, token, hub):  # noqa: F811
    call(mcp, token, "create_app", slug="radar", html=PAGE, title="Radar")
    res = call(mcp, token, "update_app_info", slug="radar", offline=True)
    assert "«radar» virker nå uten nett." in text(res)
    assert meta(hub, "radar")["offline"] is True
    res = call(mcp, token, "update_app_info", slug="radar", offline=False)
    assert "«radar» trenger nett igjen." in text(res)
    assert "offline" not in meta(hub, "radar")
    assert "virker" not in text(call(mcp, token, "update_app_info", slug="radar", title="R"))


def test_connector_create_app_offline(mcp, token, hub):  # noqa: F811
    call(mcp, token, "create_app", slug="radar", html=PAGE, title="Radar", offline=True)
    assert meta(hub, "radar")["offline"] is True
    call(mcp, token, "create_app", slug="plain", html=PAGE, title="P", offline=False)
    assert "offline" not in meta(hub, "plain")
