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


def test_theme_survives_db_error(pw_mode, hub, user_client, monkeypatch):
    def boom(con, email):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(hub.home, "get_theme", boom)
    assert user_client.get("/password").status_code == 200


def test_css_follows_the_choice(client):
    css = client.get("/static/hub.css").text
    assert ':root[data-theme="dark"]' in css and ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="light"]' in css and "color-scheme: light dark" in css
