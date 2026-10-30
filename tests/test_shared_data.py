"""Shared data: "data": "shared" in an app's meta; data/users/<e-mail>/ stays private (app/shared.py)."""
import time

from app import shared
from tests.conftest import make_client


def make_shared(hub, make_page, slug="radar", level="all"):
    make_page(slug, level)
    path = hub._meta_path(slug)
    meta = hub._read_meta(path)
    meta["data"] = "shared"
    hub._write_meta(path, meta)


def put(c, slug, path, data, **params):
    return c.put(f"/api/store/{slug}/d", params={"path": path, **params}, json=data)


def get(c, slug, path):
    return c.get(f"/api/store/{slug}/d", params={"path": path}).json()["data"]


def ids(c, slug, path):
    return [d["id"] for d in c.get(f"/api/store/{slug}/c", params={"path": path}).json()["docs"]]


def test_branch_owner_rules():
    assert shared.branch_owner("briefs", "a@t.no") == shared.SHARED
    assert shared.branch_owner("data", "a@t.no") == shared.SHARED
    assert shared.branch_owner("data/users/a@t.no", "A@t.no") == "a@t.no"
    assert shared.branch_owner("data/users/A@T.no/decks/d1/cards", "a@t.no") == "a@t.no"
    assert shared.branch_owner("data/users/b@t.no", "a@t.no") is None
    assert shared.branch_owner("data/users/a_b@t.no", "axb@t.no") is None
    assert shared.normalize("data/users/A@T.no/decks/d1/cards") == "data/users/a@t.no/decks/d1/cards"
    assert shared.normalize("Briefs") == "Briefs"


def test_admin_writes_shared_and_everyone_reads(hub, make_page, admin_client, user_client):
    make_shared(hub, make_page)
    assert put(admin_client, "radar", "briefs/b1", {"n": 1}).status_code == 200
    assert get(user_client, "radar", "briefs/b1") == {"n": 1}
    assert ids(user_client, "radar", "briefs") == ["b1"]


def test_non_admin_cannot_change_shared(hub, make_page, admin_client, user_client):
    make_shared(hub, make_page)
    put(admin_client, "radar", "briefs/b1", {"n": 1})
    assert put(user_client, "radar", "briefs/b1", {"n": 2}).status_code == 403
    assert put(user_client, "radar", "briefs/b1", {"n": 2}, merge="true").status_code == 403
    assert user_client.delete("/api/store/radar/d", params={"path": "briefs/b1"}).status_code == 403
    assert get(admin_client, "radar", "briefs/b1") == {"n": 1}


def test_own_branch_is_private_even_from_admins(hub, make_page, admin_client, user_client):
    make_shared(hub, make_page)
    assert put(user_client, "radar", "data/users/user@test.no/prefs", {"x": 1}).status_code == 200
    assert get(user_client, "radar", "data/users/User@Test.no/prefs") == {"x": 1}
    assert get(admin_client, "radar", "data/users/user@test.no/prefs") is None
    assert ids(admin_client, "radar", "data/users/user@test.no") == []
    assert put(admin_client, "radar", "data/users/user@test.no/prefs", {"x": 2}).status_code == 403
    assert "data/users/user@test.no" not in admin_client.get("/api/store/radar").json()


def test_branch_match_is_exact_in_sql(hub, make_page):
    make_shared(hub, make_page)
    with hub.db() as con:  # someone else's branch whose address differs only where LIKE would see a wildcard
        con.execute("INSERT INTO docs VALUES('radar','axb@test.no','data/users/axb@test.no','p','{}',1)")
    with hub.db() as con:
        assert hub.visible_docs(con, "radar", "a_b@test.no") == []
    assert ids(make_client("a_b@test.no"), "radar", "data/users/axb@test.no") == []


def test_personal_app_is_unchanged(hub, make_page, admin_client, user_client):
    make_page("mat")
    put(user_client, "mat", "days/d1", {"a": 1})
    assert get(admin_client, "mat", "days/d1") is None
    assert put(user_client, "mat", "data/users/someone@x.no/p", {"a": 1}).status_code == 200
    assert get(user_client, "mat", "data/users/someone@x.no/p") == {"a": 1}


def test_shared_hides_personal_rows_and_export_shows_what_you_can_read(hub, make_page, admin_client):
    make_page("radar")
    put(admin_client, "radar", "briefs/old", {"personal": True})
    path = hub._meta_path("radar")
    hub._write_meta(path, {**hub._read_meta(path), "data": "shared"})
    assert get(admin_client, "radar", "briefs/old") is None
    put(admin_client, "radar", "briefs/new", {"n": 1})
    put(admin_client, "radar", "data/users/admin@test.no/p", {"me": 1})
    assert admin_client.get("/api/store/radar").json() == {
        "briefs": {"new": {"n": 1}}, "data/users/admin@test.no": {"p": {"me": 1}}}


def test_data_setting_survives_reupload(hub, admin_client, upload):
    upload(admin_client, "radar.html", "<!doctype html><html><body>1</body></html>")
    path = hub._meta_path("radar")
    hub._write_meta(path, {**hub._read_meta(path), "data": "shared"})
    upload(admin_client, "radar.html", "<!doctype html><html><body>2</body></html>")
    assert hub._read_meta(path)["data"] == "shared"


def test_app_page_and_list_know_the_data_setting(hub, make_page, user_client):
    make_shared(hub, make_page)
    make_page("mat")
    assert 'data-shared="1"' in user_client.get("/a/radar/").text
    assert 'data-shared="0"' in user_client.get("/a/mat/").text
    modes = {a["slug"]: a["data"] for a in hub.list_artifacts("user@test.no")}
    assert modes == {"radar": "shared", "mat": "personal"}


def test_preview_counts_my_docs_and_other_users(hub, make_page, admin_client, user_client):
    make_page("radar")
    for p in ("briefs/a", "briefs/b", "meta/guide", "data/users/admin@test.no/p"):
        put(admin_client, "radar", p, {})
    put(user_client, "radar", "x/y", {})
    assert admin_client.get("/api/data-mode", params={"slug": "radar"}).json() == {
        "shared": False, "docs": 3, "collections": {"briefs": 2, "meta": 1}, "others": 1, "shared_exists": False}


def test_turn_on_with_copy_then_off_then_on_again(hub, make_page, admin_client, user_client):
    make_page("radar")
    put(admin_client, "radar", "briefs/a", {"n": 1})
    put(admin_client, "radar", "data/users/admin@test.no/p", {"me": 1})
    on = {"slug": "radar", "shared": True, "copy": True}
    assert admin_client.post("/api/data-mode", json=on).json() == {"ok": True, "shared": True, "copied": 1}
    assert get(user_client, "radar", "briefs/a") == {"n": 1}
    assert get(admin_client, "radar", "data/users/admin@test.no/p") == {"me": 1}
    admin_client.post("/api/data-mode", json={"slug": "radar", "shared": False, "copy": False})
    assert "data" not in hub._read_meta(hub._meta_path("radar"))
    assert get(admin_client, "radar", "briefs/a") == {"n": 1}  # the personal row was never touched
    assert get(user_client, "radar", "briefs/a") is None
    assert admin_client.post("/api/data-mode", json=on).json()["copied"] == 0  # shared rows exist already


def test_turn_on_and_start_empty(hub, make_page, admin_client, user_client):
    make_page("radar")
    put(admin_client, "radar", "briefs/a", {"n": 1})
    r = admin_client.post("/api/data-mode", json={"slug": "radar", "shared": True, "copy": False}).json()
    assert r["copied"] == 0 and get(user_client, "radar", "briefs/a") is None


def test_data_mode_only_for_admins_and_apps(hub, make_page, admin_client, user_client):
    make_page("radar")
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text('{"url": "https://x.no", "title": "K"}')
    assert user_client.post("/api/data-mode", json={"slug": "radar", "shared": True, "copy": False}).status_code == 403
    assert admin_client.post("/api/data-mode", json={"slug": "kort", "shared": True, "copy": False}).status_code == 404
    assert admin_client.get("/api/data-mode", params={"slug": "nope"}).status_code == 404


def test_admin_page_has_the_data_switch(hub, make_page, admin_client):
    make_page("radar")
    html = admin_client.get("/admin").text
    assert 'id="asData"' in html and 'data-slug="radar"' in html and 'data-shared="0"' in html


def test_warning_rule(hub, make_page):
    make_page("finn", "all")
    make_page("mine", "admin")
    make_page("venn", "people", ["user@test.no"])
    make_page("admins", "people", ["admin@test.no"])
    make_shared(hub, make_page, "felles")
    make_page("gammel", "all")
    make_page("ingen", "all")
    with hub.db() as con:
        for s in ("finn", "mine", "venn", "admins", "felles"):
            shared.record_write(con, s, "admin@test.no")
        shared.record_write(con, "gammel", "admin@test.no", now=int(time.time()) - 31 * 86400)
    apps = hub.list_artifacts("admin@test.no")
    assert hub.claude_filled(apps) == {"finn", "mine", "venn", "admins"}
    assert hub.claude_warned(apps) == {"finn", "venn"}


def test_admin_page_shows_the_warning(hub, make_page, admin_client):
    make_page("finn", "all")
    make_page("mine", "admin")
    with hub.db() as con:
        shared.record_write(con, "finn", "admin@test.no")
        shared.record_write(con, "mine", "admin@test.no")
    html = admin_client.get("/admin").text
    assert html.count('class="claude-warn') == 1
    assert "Claude fyller denne appen med dine personlige data." in html
    assert html.count('data-claude="1"') == 2  # the access dialog warns before "mine" is shared


def test_rename_moves_shared_rows_and_claude_writes(hub, make_page, admin_client):
    make_shared(hub, make_page)
    put(admin_client, "radar", "briefs/a", {"n": 1})
    with hub.db() as con:
        shared.record_write(con, "radar", "admin@test.no")
    assert admin_client.post("/api/edit", data={"slug": "radar", "new_slug": "radar2"}).status_code == 200
    assert get(admin_client, "radar2", "briefs/a") == {"n": 1}
    with hub.db() as con:
        assert con.execute("SELECT slug FROM claude_writes").fetchall()[0][0] == "radar2"
