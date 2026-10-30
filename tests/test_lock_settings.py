"""Settings for the code lock: choosing a code, and the switch per app (/api/lock/code, /api/lock/apps)."""
import pytest

from app import applock, i18n, main
from tests.conftest import lock, unlock

USER, ADMIN = "user@test.no", "admin@test.no"
ROUTES = ("/api/lock/code", "/api/lock/apps")


@pytest.fixture
def apps(make_page):
    make_page("notat", title="Notat")
    make_page("dagbok", title="Dagbok")
    make_page("bare-admin", "admin", title="Bare admin")


def _row(email):
    with main.db() as con:
        return applock.get(con, email)


def _ok(email, code):
    return applock.check(main.db, email, code).ok


def _put(client, slug, on, **extra):
    return client.post("/api/lock/apps", json={"slug": slug, "on": on, **extra})


def test_settings_without_a_code_offers_two_fields(user_client, apps):
    html = user_client.get("/settings").text
    assert 'name="code"' in html and 'name="repeat"' in html
    assert 'role="switch"' not in html


def test_settings_with_a_code_lists_my_apps(user_client, admin_client, apps):
    assert admin_client.post("/api/link", data={"title": "Lenke", "url": "https://example.com"}).status_code == 200
    lock(USER, "notat")
    html = user_client.get("/settings").text
    assert html.count('role="switch"') == 2  # Notat and Dagbok: no link card, no admin app
    assert 'data-slug="notat" checked' in html and 'data-slug="dagbok" checked' not in html
    assert 'data-slug="dagbok"' in html
    assert 'data-slug="bare-admin"' not in html and 'data-slug="lenke"' not in html
    assert 'name="current"' in html


def test_settings_with_a_code_and_no_apps_has_no_empty_box(user_client):
    lock(USER, "notat")
    html = user_client.get("/settings").text
    assert 'name="current"' in html and "as-group" not in html


def test_choose_a_code(user_client):
    r = user_client.post("/api/lock/code", json={"code": "0042", "repeat": "0042"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _ok(USER, "0042")


@pytest.mark.parametrize("bad", ["123", "12345", "12a4", "1234\n", "١٢٣٤", 1234, None])
def test_bad_new_codes_give_400(user_client, bad):
    r = user_client.post("/api/lock/code", json={"code": bad, "repeat": bad})
    assert r.status_code == 400
    assert _row(USER) is None


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("body", ["[]", '"x"', "5", "null", "{"])
def test_a_body_that_is_not_an_object_gives_400(user_client, route, body):
    r = user_client.post(route, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_wrong_types_give_400_and_other_bodies_are_refused(user_client, apps):
    assert user_client.post("/api/lock/code", json={"code": "1234"}).status_code == 400
    assert user_client.post("/api/lock/code", json={"code": "1234", "repeat": 1234}).status_code == 400
    lock(USER, "notat")
    assert user_client.post("/api/lock/code", json={"current": 1234, "code": "5678", "repeat": "5678"}).status_code == 400
    assert _put(user_client, "notat", "yes").status_code == 400
    assert _put(user_client, 5, True).status_code == 400
    assert _put(user_client, "notat", False, code=1234).status_code == 400
    assert user_client.post("/api/lock/code", data={"code": "1234"}).status_code == 415
    assert _ok(USER, "1234")


def test_a_mismatch_gives_400(user_client):
    r = user_client.post("/api/lock/code", json={"code": "1234", "repeat": "1235"})
    assert r.status_code == 400 and r.json()["detail"] == i18n.t("lock.err.mismatch")
    assert _row(USER) is None


def test_changing_needs_the_current_code(user_client):
    lock(USER, "notat")
    new = {"code": "5678", "repeat": "5678"}
    assert user_client.post("/api/lock/code", json=new).status_code == 403
    assert user_client.post("/api/lock/code", json={**new, "current": "9999"}).status_code == 403
    assert _ok(USER, "1234") and not _ok(USER, "5678")
    assert user_client.post("/api/lock/code", json={**new, "current": "1234"}).status_code == 200
    assert _ok(USER, "5678")


def test_a_typo_in_the_new_code_costs_no_attempt(user_client):
    lock(USER, "notat")
    r = user_client.post("/api/lock/code", json={"current": "0000", "code": "5678", "repeat": "5679"})
    assert r.status_code == 400
    assert _row(USER)["fails"] == 0


def test_the_new_code_may_not_be_the_current_one(user_client):
    lock(USER, "notat")
    r = user_client.post("/api/lock/code", json={"current": "1234", "code": "1234", "repeat": "1234"})
    assert r.status_code == 400 and r.json()["detail"] == i18n.t("lock.err.same")


def test_changing_locks_every_app(user_client, apps):
    lock(USER, "notat")
    assert unlock(user_client, "notat").status_code == 303
    assert user_client.get("/a/notat/").status_code == 200
    r = user_client.post("/api/lock/code", json={"current": "1234", "code": "5678", "repeat": "5678"})
    assert r.status_code == 200
    assert user_client.get("/a/notat/").status_code == 423


def test_changing_accepts_the_one_time_code(user_client):
    lock(USER, "notat")
    with main.db() as con:
        applock.set_code(con, USER, "4321", must_change=True)
    r = user_client.post("/api/lock/code", json={"current": "4321", "code": "5678", "repeat": "5678"})
    assert r.status_code == 200
    assert _row(USER)["must_change"] == 0


def test_lock_on_needs_no_code_and_is_at_once(user_client, apps):
    with main.db() as con:
        applock.set_code(con, USER, "1234")
    r = _put(user_client, "notat", True)
    assert r.status_code == 200 and r.json() == {"ok": True, "on": True}
    assert user_client.get("/a/notat/").status_code == 423


def test_lock_on_without_a_code_is_refused(user_client, apps):
    r = _put(user_client, "notat", True)
    assert r.status_code == 400 and r.json()["detail"] == i18n.t("lock.err.no_code")


def test_a_link_card_cannot_be_locked(user_client, admin_client, apps):
    assert admin_client.post("/api/link", data={"title": "Lenke", "url": "https://example.com"}).status_code == 200
    with main.db() as con:
        applock.set_code(con, USER, "1234")
        applock.set_code(con, ADMIN, "1234")
    assert _put(admin_client, "lenke", True).status_code == 404
    assert _put(user_client, "bare-admin", True).status_code == 404
    assert _put(user_client, "finnes-ikke", True).status_code == 404


def test_lock_off_needs_the_code(user_client, apps):
    lock(USER, "notat")
    assert _put(user_client, "notat", False).status_code == 403
    assert _put(user_client, "notat", False, code="0000").status_code == 403
    assert user_client.get("/a/notat/").status_code == 423
    r = _put(user_client, "notat", False, code="1234")
    assert r.status_code == 200 and r.json() == {"ok": True, "on": False}
    assert user_client.get("/a/notat/").status_code == 200


def test_settings_and_the_screen_share_the_limit(user_client, apps):
    lock(USER, "notat")
    for _ in range(4):
        assert _put(user_client, "notat", False, code="0000").status_code == 403
    unlock(user_client, "notat", "0000")  # the fifth wrong try, on the screen
    r = _put(user_client, "notat", False, code="1234")
    assert r.status_code == 429 and "15" in r.json()["detail"]
    assert "15" in unlock(user_client, "notat").text


def test_five_wrong_off_attempts_block(user_client, apps):
    lock(USER, "notat")
    codes = [_put(user_client, "notat", False, code="0000").status_code for _ in range(5)]
    assert codes == [403, 403, 403, 403, 429]
    assert "15" in unlock(user_client, "notat").text


@pytest.mark.parametrize("route", ROUTES)
def test_logged_out_gives_401(client, route):
    assert client.post(route, json={}).status_code == 401


def test_the_choice_is_per_user(user_client, admin_client, apps):
    lock(USER, "notat")
    assert user_client.get("/a/notat/").status_code == 423
    assert admin_client.get("/a/notat/").status_code == 200


def test_a_one_time_code_cannot_turn_the_lock_off(user_client, apps):
    lock(USER, "notat")
    with main.db() as con:
        one_time = applock.reset(con, USER)
    r = _put(user_client, "notat", False, code=one_time)
    assert r.status_code == 403 and i18n.t("lock.err.pick_new") in r.text
    with main.db() as con:
        assert applock.is_locked(con, USER, "notat")
    assert _row(USER)["must_change"] == 1


def test_a_normal_code_still_turns_the_lock_off(user_client, apps):
    lock(USER, "notat")
    assert _put(user_client, "notat", False, code="1234").status_code == 200
    with main.db() as con:
        assert not applock.is_locked(con, USER, "notat")


def test_a_one_time_code_still_works_as_the_current_code(user_client, apps):
    lock(USER, "notat")
    with main.db() as con:
        one_time = applock.reset(con, USER)
    r = user_client.post("/api/lock/code", json={"current": one_time, "code": "9999", "repeat": "9999"})
    assert r.status_code == 200 and _ok(USER, "9999")
