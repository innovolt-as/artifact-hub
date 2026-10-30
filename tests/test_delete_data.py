"""Slett mine data on the settings page: the user's own data in every app goes, everything else stays."""
import pytest

from app import applock, main
from tests.conftest import lock, make_client

URL = "/api/me/delete-data"
USER, OTHER = "user@test.no", "admin@test.no"


def add_key(email, app="notat", key="k"):
    with main.db() as con:
        con.execute("INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?)", (email, app, key, "1", 0))


def count(table, column, value):
    with main.db() as con:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (value,)).fetchone()[0]


@pytest.fixture
def seeded(make_page):
    make_page("notat")
    main.doc_set("notat", USER, "a/b", {"x": 1})
    main.doc_set("notat", OTHER, "a/b", {"x": 2})
    add_key(USER)
    add_key(OTHER)


def test_my_documents_and_keys_go(seeded, user_client):
    r = user_client.post(URL, json={"confirm": "SLETT"})
    assert r.status_code == 200 and r.json() == {"ok": True, "docs": 1, "keys": 1}
    assert count("docs", "owner", USER) == 0
    assert count("app_data", "email", USER) == 0


def test_other_peoples_data_stays(seeded, user_client):
    user_client.post(URL, json={"confirm": "SLETT"})
    assert count("docs", "owner", OTHER) == 1
    assert count("app_data", "email", OTHER) == 1


def test_shared_documents_stay_and_my_branch_goes(make_page, user_client):
    make_page("felles")
    main.set_data_mode("felles", True)
    main.doc_set("felles", OTHER, "news/1", {"t": "for alle"})
    main.doc_set("felles", USER, f"data/users/{USER}/mine", {"t": "privat"})
    assert user_client.post(URL, json={"confirm": "SLETT"}).json()["docs"] == 1
    assert main.doc_get("felles", OTHER, "news/1") == {"t": "for alle"}
    assert main.doc_get("felles", USER, f"data/users/{USER}/mine") is None


def test_data_of_an_app_that_is_gone_goes_too(user_client):
    with main.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES('borte', ?, 'a', 'b', '{}', 0)", (USER,))
    assert user_client.post(URL, json={"confirm": "SLETT"}).json()["docs"] == 1


def test_settings_and_locks_stay(seeded, user_client):
    assert user_client.post("/api/prefs/theme", json={"theme": "dark"}).status_code == 200
    lock(USER, "notat")
    assert user_client.post(URL, json={"code": "1234"}).status_code == 200
    with main.db() as con:
        assert main.home.get_theme(con, USER) == "dark"
        assert applock.get(con, USER) is not None
        assert applock.is_locked(con, USER, "notat")


def test_the_connector_note_goes(seeded, user_client):
    with main.db() as con:
        main.shared.record_write(con, "notat", USER)
    user_client.post(URL, json={"confirm": "SLETT"})
    assert count("claude_writes", "email", USER) == 0


@pytest.mark.parametrize("body", [{}, {"confirm": ""}, {"confirm": "slett"}, {"confirm": 1}, {"code": "1234"}])
def test_without_a_code_it_needs_the_word(seeded, user_client, body):
    r = user_client.post(URL, json=body)
    assert r.status_code == 400
    assert count("docs", "owner", USER) == 1


def test_english_uses_its_own_word(seeded, user_client, english):
    assert user_client.post(URL, json={"confirm": "SLETT"}).status_code == 400
    assert user_client.post(URL, json={"confirm": "DELETE"}).status_code == 200


@pytest.mark.parametrize("body", [{}, {"code": "9999"}, {"code": 1234}, {"code": None}, {"confirm": "SLETT"}])
def test_with_a_code_it_needs_the_code(seeded, user_client, body):
    lock(USER, "notat")
    r = user_client.post(URL, json=body)
    assert r.status_code == 403
    assert count("docs", "owner", USER) == 1


def test_the_right_code_deletes(seeded, user_client):
    lock(USER, "notat")
    assert user_client.post(URL, json={"code": "1234"}).status_code == 200
    assert count("docs", "owner", USER) == 0


def test_the_attempt_limit_is_shared(seeded, user_client):
    lock(USER, "notat")
    codes = [user_client.post(URL, json={"code": "9999"}).status_code for _ in range(5)]
    assert codes == [403, 403, 403, 403, 429]
    assert user_client.post(URL, json={"code": "1234"}).status_code == 429
    assert count("docs", "owner", USER) == 1


def test_a_one_time_code_only_chooses_a_new_code(seeded, user_client):
    lock(USER, "notat")
    with main.db() as con:
        code = applock.reset(con, USER)
    r = user_client.post(URL, json={"code": code})
    assert r.status_code == 403 and r.json()["detail"] == main.i18n.t("lock.err.pick_new")
    assert count("docs", "owner", USER) == 1


def test_logged_out_is_401(client):
    assert client.post(URL, json={"confirm": "SLETT"}).status_code == 401


def test_a_form_post_is_refused(seeded, user_client):
    assert user_client.post(URL, data={"confirm": "SLETT"}).status_code == 415
    assert count("docs", "owner", USER) == 1


def test_a_body_that_is_not_an_object_is_400(user_client):
    assert user_client.post(URL, json=["SLETT"]).status_code == 400


def test_a_capitalised_session_finds_its_data(seeded):
    assert make_client("User@Test.no").post(URL, json={"confirm": "SLETT"}).json() == {"ok": True, "docs": 1, "keys": 1}


def test_settings_offers_logout_and_delete(user_client):
    html = user_client.get("/settings").text
    assert 'action="/logout"' in html and 'id="deleteData"' in html


@pytest.mark.parametrize("path", ["/", "/admin", "/admin/upload"])
def test_the_top_bar_has_no_logout(admin_client, path):
    assert 'action="/logout"' not in admin_client.get(path).text


def test_the_dialog_asks_for_the_word_without_a_code(user_client):
    html = user_client.get("/settings").text
    assert 'name="confirm"' in html and "SLETT" in html


def test_the_dialog_asks_for_the_code_with_one(make_page, user_client):
    make_page("notat")
    lock(USER, "notat")
    html = user_client.get("/settings").text
    dialog = html[html.index('id="deleteAsk"'):]
    assert 'name="code"' in dialog and 'name="confirm"' not in dialog


def test_settings_in_english(user_client, english):
    html = user_client.get("/settings").text
    assert "Delete my data" in html and "Log out" in html
