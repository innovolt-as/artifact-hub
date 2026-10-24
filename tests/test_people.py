"""Invited people ("Personer" on the admin page) can log in; removing them takes them off every app."""
from app import access


def test_invited_can_log_in(hub, client, admin_client):
    assert not hub.email_allowed("ny@test.no")
    r = admin_client.post("/api/people/invite", json={"email": " Ny@Test.no "})
    assert r.status_code == 200 and r.json()["email"] == "ny@test.no"
    assert hub.email_allowed("ny@test.no") and hub.email_allowed("NY@test.no")
    client.post("/login", data={"email": "ny@test.no"})
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM magic_tokens WHERE email='ny@test.no'").fetchone()[0] == 1


def test_invite_rejects(admin_client, user_client):
    assert admin_client.post("/api/people/invite", json={"email": "ikke-epost"}).status_code == 400
    assert admin_client.post("/api/people/invite", json={"email": "Admin@test.no"}).status_code == 400
    assert user_client.post("/api/people/invite", json={"email": "x@y.no"}).status_code == 403
    assert admin_client.post("/api/people/invite", data={"email": "x@y.no"}).status_code == 415


def test_remove_person_everywhere(hub, make_page, admin_client):
    admin_client.post("/api/people/invite", json={"email": "ny@test.no"})
    make_page("p", "people", ["ny@test.no", "venn@test.no"])
    make_page("q", "all", ["ny@test.no"])  # remembered list on an "Alle" app is cleaned too
    r = admin_client.post("/api/people/remove", json={"email": "NY@test.no"})
    assert r.status_code == 200 and sorted(r.json()["apps"]) == ["p", "q"]
    assert not hub.email_allowed("ny@test.no")
    assert access.people(hub._read_meta(hub._meta_path("p"))) == ["venn@test.no"]
    assert admin_client.post("/api/people/remove", json={"email": "ny@test.no"}).status_code == 404


def test_unknown_email_still_told_sent(client):
    r = client.post("/login", data={"email": "fremmed@x.no"})
    assert r.status_code == 200 and "fremmed@x.no" in r.text
