"""An admin session on a lent phone: what needs the app unlocked, and resetting someone else's code."""
import json
import logging

import pytest

from app import access, applock, main
from tests.conftest import lock, make_client, unlock

ADMIN, USER = "admin@test.no", "user@test.no"
HTML = "<!doctype html><html><head><title>t</title></head><body>{}</body></html>"


@pytest.fixture
def locked(hub):
    """The page notat, locked for the admin with the code 1234, with one document in its data."""
    hub.save_page("notat", HTML.format("old"), create=True, private=False, title="Notat")
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES(?,?,?,?,?,0)",
                    ("notat", ADMIN, "kolleksjon", "a", "{}"))
    lock(ADMIN, "notat")


def meta():
    return json.loads(main._meta_path("notat").read_text())


def docs(slug):
    with main.db() as con:
        return con.execute("SELECT COUNT(*) FROM docs WHERE slug=?", (slug,)).fetchone()[0]


def edit(c, **form):
    return c.post("/api/edit", data={"slug": "notat", **form})


def post_upload(c, name="notat.html", **form):
    return c.post("/api/upload", files={"file": (name, HTML.format("new").encode())}, data=form)


ACTIONS = {
    "rename": lambda c: edit(c, new_slug="notat2"),
    "datamode_get": lambda c: c.get("/api/data-mode?slug=notat"),
    "datamode_set": lambda c: c.post("/api/data-mode", json={"slug": "notat", "shared": True, "copy": True}),
    "delete": lambda c: c.post("/api/delete", data={"slug": "notat"}),
    "upload": lambda c: post_upload(c),
    "access": lambda c: c.post("/api/access", json={"slug": "notat", "level": "admin", "people": []}),
}


def test_a_new_address_needs_unlocking(locked, admin_client):
    before = meta()
    r = edit(admin_client, new_slug="notat2", title="Annet")
    assert r.status_code == 423 and r.json()["detail"] == main.i18n.t("lock.unlock_first")
    assert main._meta_path("notat") and not main._meta_path("notat2")
    assert docs("notat") == 1 and meta() == before


def test_name_and_icon_without_a_new_address_are_free(locked, admin_client):
    assert edit(admin_client, title="Annet", emoji="x").status_code == 200
    assert meta()["title"] == "Annet"


def test_the_banner_switch_is_free(locked, admin_client):
    assert admin_client.post("/api/toggle-banner", data={"slug": "notat"}).status_code == 200


def test_data_mode_needs_unlocking(locked, admin_client):
    before = meta()
    r = admin_client.get("/api/data-mode?slug=notat")
    assert r.status_code == 423 and "kolleksjon" not in r.text
    r = admin_client.post("/api/data-mode", json={"slug": "notat", "shared": True, "copy": True})
    assert r.status_code == 423
    assert meta() == before and docs("notat") == 1


def test_delete_needs_unlocking(locked, admin_client):
    assert admin_client.post("/api/delete", data={"slug": "notat"}).status_code == 423
    assert (main.ARTIFACTS_DIR / "notat.html").exists()


@pytest.mark.parametrize("name, form", [("notat.html", {}), ("other.html", {"slug": "notat"})])
def test_upload_over_a_locked_app_needs_unlocking(locked, admin_client, name, form):
    assert post_upload(admin_client, name, **form).status_code == 423
    assert "old" in (main.ARTIFACTS_DIR / "notat.html").read_text()


def test_a_rejected_file_does_not_remove_a_locked_app(locked, admin_client):
    assert post_upload(admin_client, "notat.txt").status_code == 423
    assert unlock(admin_client, "notat").status_code == 303
    assert admin_client.get("/a/notat/").status_code == 200


@pytest.mark.parametrize("level", ["all", "people", "admin"])
def test_access_needs_unlocking(locked, admin_client, level):
    before = meta()
    r = admin_client.post("/api/access", json={"slug": "notat", "level": level, "people": ["x@test.no"]})
    assert r.status_code == 423
    assert meta() == before


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_each_works_after_unlock(locked, admin_client, action):
    unlock(admin_client, "notat")
    assert ACTIONS[action](admin_client).status_code == 200


def test_upload_token_and_delete_token_pass(locked, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_TOKEN", "t")
    c = make_client()
    h = {"Authorization": "Bearer t"}
    r = c.post("/api/upload", files={"file": ("notat.html", HTML.format("new").encode())}, headers=h)
    assert r.status_code == 200
    assert c.post("/api/delete", data={"slug": "notat"}, headers=h).status_code == 200


def test_a_lock_on_another_admins_list_does_not_stop_me(hub, admin_client):
    hub.save_page("notat", HTML.format("old"), create=True, private=False, title="Notat")
    lock(USER, "notat")
    assert edit(admin_client, new_slug="notat2").status_code == 200


def test_upload_to_an_address_with_no_app_is_free(locked, admin_client):
    unlock(admin_client, "notat")
    assert admin_client.post("/api/delete", data={"slug": "notat"}).status_code == 200
    fresh = make_client(ADMIN)
    assert post_upload(fresh).status_code == 200
    assert fresh.get("/a/notat/").status_code == 423  # the code screen: the lock survived


def test_the_lock_follows_a_rename_and_the_unlock_does_not(locked, admin_client, user_client):
    lock(USER, "notat")
    unlock(admin_client, "notat")
    assert edit(admin_client, new_slug="notat2").status_code == 200
    assert admin_client.get("/a/notat2/").status_code == 423
    assert user_client.get("/a/notat2/").status_code == 423


def test_the_lock_survives_delete(locked, admin_client):
    unlock(admin_client, "notat")
    admin_client.post("/api/delete", data={"slug": "notat"})
    with main.db() as con:
        assert applock.is_locked(con, ADMIN, "notat")


def code_hash(email):
    with main.db() as con:
        return applock.get(con, email)["hash"]


def test_reset_for_someone_else(hub, admin_client, user_client):
    lock(USER, "notat")
    hub.save_page("notat", HTML.format("x"), create=True, private=False, title="Notat")
    r = admin_client.post("/api/people/lock-reset", json={"email": USER})
    assert r.status_code == 200 and r.json()["ok"]
    new = r.json()["code"]
    assert len(new) == 4 and new.isdigit()
    if new != "1234":
        assert unlock(user_client, "notat", "1234").status_code == 423
        assert user_client.get("/a/notat/").status_code == 423
    out = unlock(user_client, "notat", new)
    assert out.status_code == 200 and 'name="new1"' in out.text


def test_reset_refuses_myself(hub, admin_client):
    lock(ADMIN, "notat")
    before = code_hash(ADMIN)
    r = admin_client.post("/api/people/lock-reset", json={"email": ADMIN})
    assert r.status_code == 403 and r.json()["detail"] == main.i18n.t("lock.err.not_yourself")
    assert code_hash(ADMIN) == before


def test_reset_refuses_myself_with_capitals(hub, admin_client):
    lock(ADMIN, "notat")
    before = code_hash(ADMIN)
    assert admin_client.post("/api/people/lock-reset", json={"email": "ADMIN@test.no"}).status_code == 403
    assert code_hash(ADMIN) == before


def test_reset_without_a_code_is_404(admin_client):
    r = admin_client.post("/api/people/lock-reset", json={"email": USER})
    assert r.status_code == 404 and r.json()["detail"] == main.i18n.t("lock.err.no_code_for")


def test_reset_needs_admin(user_client):
    lock(USER, "notat")
    assert user_client.post("/api/people/lock-reset", json={"email": USER}).status_code == 403


def test_people_page_offers_reset_only_for_people_with_a_code(hub, admin_client):
    lock(USER, "notat")
    lock(ADMIN, "notat")
    with hub.db() as con:
        access.invite(con, "venn@test.no")
    html = admin_client.get("/admin/people").text
    assert html.count('class="small lockreset"') == 1
    assert 'class="small lockreset" data-email="user@test.no"' in html
    assert "venn@test.no" in html and 'lockreset" data-email="venn@test.no"' not in html
    assert 'lockreset" data-email="admin@test.no"' not in html


def test_other_admins_with_a_code_are_on_the_people_page(hub, admin_client, monkeypatch):
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN, "admin2@test.no"})
    lock("admin2@test.no", "notat")
    assert 'lockreset" data-email="admin2@test.no"' in admin_client.get("/admin/people").text


def test_the_code_is_never_logged(hub, admin_client, user_client, caplog):
    lock(USER, "notat", "7351")
    with caplog.at_level(logging.INFO):
        code = admin_client.post("/api/people/lock-reset", json={"email": USER}).json()["code"]
        unlock(user_client, "notat", code)
        unlock(user_client, "notat", "7351")
    assert code not in caplog.text and "7351" not in caplog.text
