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


# ---------------------------------------------------------------- what the service worker gets from the server
import json  # noqa: E402
import re  # noqa: E402

from tests.conftest import lock, make_client, unlock  # noqa: E402

USER = "user@test.no"
PRE = {"X-Hub-Precache": "1", "sec-fetch-dest": "empty"}


def _page(hub, slug, offline=True):
    hub.save_page(slug, "<html><head><title>t</title></head><body>x</body></html>", create=True, private=False, title=slug)
    if offline:
        hub.set_offline(slug, True)


def _visits(hub, slug):
    with hub.db() as con:
        return con.execute("SELECT COUNT(*) FROM visits WHERE slug=?", (slug,)).fetchone()[0]


def test_precache_does_not_count_as_visit(hub):
    _page(hub, "a")
    c = make_client(USER)
    assert c.get("/a/a/", headers=PRE).status_code == 200
    assert _visits(hub, "a") == 0
    assert c.get("/a/a/").status_code == 200
    assert _visits(hub, "a") == 1


def test_precache_gets_the_banner(hub):
    _page(hub, "a")
    assert "<hub-banner" in make_client(USER).get("/a/a/", headers=PRE).text


def test_precache_refuses_unmarked(hub):
    _page(hub, "b", offline=False)
    c = make_client(USER)
    assert c.get("/a/b/", headers=PRE).status_code == 404
    assert c.get("/a/b/").status_code == 200


def test_precache_refuses_locked_even_unlocked(hub):
    _page(hub, "a")
    lock(USER, "a")
    c = make_client(USER)
    assert c.get("/a/a/", headers=PRE).status_code == 423
    assert unlock(c, "a").status_code == 303
    assert c.get("/a/a/").status_code == 200
    assert c.get("/a/a/", headers=PRE).status_code == 423


def test_precache_folder_files_as_normal(hub, admin_client, upload):
    upload(admin_client, "f.zip", _folder(), title="F")
    hub.set_offline("f", True)
    r = admin_client.get("/a/f/index.html", headers=PRE)
    assert r.status_code == 200 and "<hub-banner" in r.text
    assert admin_client.get("/a/f/missing.png", headers=PRE).status_code == 404


def test_shim_marks_offline_apps(hub):
    _page(hub, "a")
    _page(hub, "b", offline=False)
    _page(hub, "c")
    lock(USER, "c")
    c = make_client(USER)
    tag = lambda slug: re.search(r'<script src="/static/hub\.js"[^>]*>', c.get(f"/a/{slug}/", headers={"sec-fetch-dest": "empty"}).text).group(0)  # noqa: E731
    assert ' data-offline="1"' in tag("a")
    assert "data-offline" not in tag("b")
    unlock(c, "c")
    assert "data-offline" not in tag("c")


def test_front_page_lists_offline_apps(hub, admin_client):
    for slug in ("a", "b", "c"):
        _page(hub, slug, offline=slug != "b")
    lock(USER, "c")
    admin_client.post("/api/link", data={"title": "L", "url": "https://example.com"})
    c = make_client(USER)
    r = c.get("/")
    strings = json.loads(re.search(r'id="__hub_strings">(.*?)</script>', r.text, re.S).group(1))
    assert strings["offline_apps"] == ["a"]


def test_sw_served_at_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["service-worker-allowed"] == "/"
