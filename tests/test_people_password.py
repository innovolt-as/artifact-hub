from tests.conftest import set_pw


def test_invite_requires_password_in_password_mode(pw_mode, hub, admin_client):
    r = admin_client.post("/api/people/invite", json={"email": "ny@test.no"})
    assert r.status_code == 400 and not hub.email_allowed("ny@test.no")
    r = admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "kort"})
    assert r.status_code == 400
    r = admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-passord"})
    assert r.status_code == 200 and hub.email_allowed("ny@test.no")
    with hub.db() as con:
        row = hub.passwd.get(con, "ny@test.no")
        assert row["must_change"] == 1 and hub.passwd.verify_password("temp-passord", row["hash"])


def test_reinvite_resets_temporary_password(pw_mode, hub, admin_client):
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-passord"})
    set_pw("ny@test.no", "eget passord")
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-to-passord"})
    with hub.db() as con:
        row = hub.passwd.get(con, "ny@test.no")
        assert row["must_change"] == 1 and hub.passwd.verify_password("temp-to-passord", row["hash"])


def test_people_password_endpoint(pw_mode, hub, admin_client, user_client):
    assert admin_client.post("/api/people/password", json={"email": "fremmed@x.no", "password": "temp-passord"}).status_code == 404
    assert user_client.post("/api/people/password", json={"email": "user@test.no", "password": "temp-passord"}).status_code == 403
    r = admin_client.post("/api/people/password", json={"email": "user@test.no", "password": "temp-passord"})  # ALLOWED_EMAILS
    assert r.status_code == 200
    r = admin_client.post("/api/people/password", json={"email": "admin@test.no", "password": "temp-passord"})  # admin self
    assert r.status_code == 200
    with hub.db() as con:
        assert hub.passwd.get(con, "admin@test.no")["must_change"] == 1


def test_remove_deletes_password(pw_mode, hub, admin_client):
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-passord"})
    admin_client.post("/api/people/remove", json={"email": "ny@test.no"})
    with hub.db() as con:
        assert hub.passwd.get(con, "ny@test.no") is None


def test_admin_page_shows_status_and_controls(pw_mode, hub, admin_client):
    admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "temp-passord"})
    html = admin_client.get("/admin").text
    assert "må byttes" in html and "Nytt midlertidig passord" in html and 'id="genPw"' in html
    assert "user@test.no" in html and "mangler" in html  # ALLOWED_EMAILS without a password row


def test_default_mode_admin_untouched(admin_client, hub):
    r = admin_client.post("/api/people/invite", json={"email": "ny@test.no"})
    assert r.status_code == 200
    assert admin_client.post("/api/people/password", json={"email": "ny@test.no", "password": "temp-passord"}).status_code == 404
    html = admin_client.get("/admin").text
    assert "Nytt midlertidig passord" not in html and 'name="password"' not in html
