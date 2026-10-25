from tests.conftest import make_client, set_pw


def _login(client, email, password, next="/"):
    return client.post("/login", data={"email": email, "password": password, "next": next})


def test_pending_user_sets_new_password_and_lands(pw_mode, hub, client):
    set_pw("user@test.no", "temp-passord", must_change=True)
    _login(client, "user@test.no", "temp-passord", next="/admin")
    html = client.get("/password?next=/admin").text
    assert "Velg et nytt passord" in html and 'name="current"' not in html
    r = client.post("/password", data={"new1": "helt nytt passord", "new2": "helt nytt passord", "next": "/admin"})
    assert r.status_code == 302 and r.headers["location"] == "/admin"
    assert client.get("/api/me").status_code == 200
    with hub.db() as con:
        row = hub.passwd.get(con, "user@test.no")
        assert row["must_change"] == 0 and hub.passwd.verify_password("helt nytt passord", row["hash"])
        assert con.execute("SELECT COUNT(*) FROM logins WHERE email='user@test.no'").fetchone()[0] == 1


def test_pending_validation_messages(pw_mode, hub, client):
    set_pw("user@test.no", "temp-passord", must_change=True)
    _login(client, "user@test.no", "temp-passord")
    for data, msg in [({"new1": "kort", "new2": "kort"}, "minst 10 tegn"),
                      ({"new1": "a" * 201, "new2": "a" * 201}, "for langt"),
                      ({"new1": "passord-en-123", "new2": "passord-to-123"}, "ikke like"),
                      ({"new1": "temp-passord", "new2": "temp-passord"}, "annet passord")]:
        r = client.post("/password", data={**data, "next": "/"})
        assert r.status_code == 200 and msg in r.text
    assert client.get("/api/me").status_code == 401


def test_pending_cookie_dies_when_admin_resets(pw_mode, hub, client):
    set_pw("user@test.no", "temp-1", must_change=True)
    _login(client, "user@test.no", "temp-1")
    set_pw("user@test.no", "temp-2", must_change=True)  # admin set a new temporary password
    r = client.post("/password", data={"new1": "helt nytt passord", "new2": "helt nytt passord", "next": "/"})
    assert r.status_code == 403
    assert client.get("/api/me").status_code == 401


def test_pending_cookie_dies_when_person_removed(pw_mode, hub, client, admin_client):
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-passord"})
    _login(client, "ny@test.no", "temp-passord")
    admin_client.post("/api/people/remove", json={"email": "ny@test.no"})
    r = client.post("/password", data={"new1": "helt nytt passord", "new2": "helt nytt passord", "next": "/"})
    assert r.status_code == 403


def test_logged_in_user_changes_password(pw_mode, hub, user_client):
    set_pw("user@test.no", "passord123")
    html = user_client.get("/password").text
    assert "Bytt passord" in html and 'name="current"' in html
    r = user_client.post("/password", data={"current": "feil", "new1": "helt nytt passord", "new2": "helt nytt passord"})
    assert r.status_code == 200 and "Feil passord" in r.text
    r = user_client.post("/password", data={"current": "passord123", "new1": "helt nytt passord", "new2": "helt nytt passord"})
    assert r.status_code == 302
    with hub.db() as con:
        assert hub.passwd.verify_password("helt nytt passord", hub.passwd.get(con, "user@test.no")["hash"])


def test_link_only_in_password_mode(hub, user_client, monkeypatch):
    assert "Bytt passord" not in user_client.get("/").text
    monkeypatch.setattr(hub, "LOGIN_MODE", "password")
    assert "Bytt passord" in user_client.get("/").text


def test_password_routes_404_in_default_mode(client, user_client):
    assert user_client.get("/password").status_code == 404
    assert user_client.post("/password", data={"new1": "x" * 10, "new2": "x" * 10}).status_code == 404
