import sqlite3

import pytest


def test_theme_default_set_and_invalid(hub):
    with hub.db() as con:
        assert hub.home.get_theme(con, "x@t.no") == "auto"
        hub.home.set_theme(con, "x@t.no", "dark")
        assert hub.home.get_theme(con, "X@t.no") == "dark"
    with hub.db() as con, pytest.raises(ValueError):
        hub.home.set_theme(con, "x@t.no", "rosa")


def test_prefs_theme_api(hub, user_client, client):
    r = user_client.post("/api/prefs/theme", json={"theme": "light"})
    assert r.status_code == 200 and r.json() == {"ok": True, "theme": "light"}
    assert user_client.post("/api/prefs/theme", json={"theme": "rosa"}).status_code == 400
    assert user_client.post("/api/prefs/theme", json=[]).status_code == 400
    assert client.post("/api/prefs/theme", json={"theme": "dark"}).status_code == 401


def test_html_gets_data_theme_only_when_chosen(pw_mode, hub, user_client):
    assert "data-theme" not in user_client.get("/").text.split("<head>")[0]
    user_client.post("/api/prefs/theme", json={"theme": "dark"})
    assert 'data-theme="dark"' in user_client.get("/").text.split("<head>")[0]
    assert 'data-theme="dark"' in user_client.get("/password").text.split("<head>")[0]
    user_client.post("/api/prefs/theme", json={"theme": "auto"})
    assert "data-theme" not in user_client.get("/").text.split("<head>")[0]


def test_bad_stored_theme_is_auto(hub, user_client):
    with hub.db() as con:
        con.execute("INSERT INTO prefs(email, key, value) VALUES('user@test.no', 'theme', '\"rosa\"')")
    r = user_client.get("/")
    assert r.status_code == 200 and "data-theme" not in r.text.split("<head>")[0]


def test_login_page_follows_the_device(client):
    assert "data-theme" not in client.get("/login").text.split("<head>")[0]


THEME_JS = '<script src="/static/theme.js"'


def test_theme_script_is_on_the_hubs_pages_but_not_on_apps_or_login(make_page, user_client, client):
    assert THEME_JS in user_client.get("/").text and THEME_JS in user_client.get("/settings").text
    assert THEME_JS not in client.get("/login").text
    make_page("appen")
    app = user_client.get("/a/appen/").text
    assert "/static/pull.js" in app and "theme.js" not in app


def test_a_restored_page_gets_the_theme_chosen_since(client):
    settings = client.get("/static/settings.js").text
    assert 'sessionStorage.setItem("hub-theme"' in settings
    assert 'saved = root.dataset.theme || "auto";' in settings  # settings itself restored: the buttons follow
    js = client.get("/static/theme.js").text
    assert "e.persisted" in js and 'sessionStorage.getItem("hub-theme")' in js


def test_the_restore_stays_out_of_pull_js(client):
    # pull.js is injected into every app page too, and the theme must never touch apps
    assert "hub-theme" not in client.get("/static/pull.js").text


def test_theme_survives_db_error(pw_mode, hub, user_client, monkeypatch):
    def boom(con, email):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(hub.home, "get_theme", boom)
    assert user_client.get("/password").status_code == 200


def test_css_follows_the_choice(client):
    css = client.get("/static/hub.css").text
    assert ':root[data-theme="dark"]' in css and ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="light"]' in css and "color-scheme: light dark" in css


def test_bad_stored_theme_text_is_auto(hub, user_client):
    with hub.db() as con:
        con.execute("INSERT INTO prefs(email, key, value) VALUES('user@test.no', 'theme', 'not json{')")
    for path in ("/", "/settings"):
        r = user_client.get(path)
        assert r.status_code == 200 and "data-theme" not in r.text.split("<head>")[0]
    assert 'value="auto" checked' in user_client.get("/settings").text


def test_settings_needs_login(client):
    r = client.get("/settings")
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_settings_for_every_user(user_client, friend_client):
    assert user_client.get("/settings").status_code == 200
    assert friend_client.get("/settings").status_code == 200


def test_settings_shows_the_choice(user_client):
    user_client.post("/api/prefs/theme", json={"theme": "dark"})
    html = user_client.get("/settings").text
    assert 'value="dark" checked' in html and 'value="auto" checked' not in html
    assert '/static/settings.js' in html


def test_top_row_links_to_settings_and_nothing_more(user_client, admin_client):
    home = user_client.get("/").text
    assert 'class="who" href="/settings"' in home and 'class="who-icon" href="/settings"' in home
    admin = admin_client.get("/admin").text
    assert 'class="who" href="/settings"' in admin and 'class="who-icon" href="/settings"' in admin


def test_change_password_moved_to_settings(user_client, pw_mode):
    assert 'href="/password"' not in user_client.get("/").text
    assert 'href="/password"' in user_client.get("/settings").text


def test_no_change_password_without_password_mode(user_client):
    assert 'href="/password"' not in user_client.get("/settings").text
