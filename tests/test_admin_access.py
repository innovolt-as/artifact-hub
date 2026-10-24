"""Admin page: the access dialog per app (/api/access) and the "Personer" card."""
from app import access


def _meta(hub, slug):
    return hub._read_meta(hub._meta_path(slug))


def test_set_people_invites_and_drops_admin(hub, make_page, admin_client):
    make_page("p")
    r = admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": ["Ny@Test.no", "admin@test.no"]})
    assert r.status_code == 200 and r.json()["label"] == "👥 1 person"
    assert access.level(_meta(hub, "p")) == "people" and access.people(_meta(hub, "p")) == ["ny@test.no"]
    assert hub.email_allowed("ny@test.no")


def test_widening_keeps_list_and_login(hub, make_page, admin_client):
    make_page("p")
    admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": ["ny@test.no"]})
    r = admin_client.post("/api/access", json={"slug": "p", "level": "all", "people": ["ny@test.no"]})
    assert r.json()["label"] == "🌍 Alle" and access.people(_meta(hub, "p")) == ["ny@test.no"]
    assert hub.email_allowed("ny@test.no")


def test_access_on_link_card(hub, admin_client):
    (hub.ARTIFACTS_DIR / "k.link.json").write_text('{"title": "K", "url": "https://x.no/"}')
    assert admin_client.post("/api/access", json={"slug": "k", "level": "admin", "people": []}).status_code == 200
    assert _meta(hub, "k")["admin_only"] is True


def test_access_rejects(make_page, admin_client, user_client):
    make_page("p")

    def post(c, body):
        return c.post("/api/access", json=body)
    assert post(admin_client, {"slug": "nei", "level": "all", "people": []}).status_code == 404
    assert post(admin_client, {"slug": "p", "level": "noen", "people": []}).status_code == 400
    r = post(admin_client, {"slug": "p", "level": "people", "people": ["ikke epost"]})
    assert r.status_code == 400 and "ikke epost" in r.json()["detail"]
    assert post(user_client, {"slug": "p", "level": "all", "people": []}).status_code == 403
    assert admin_client.post("/api/access", data={"slug": "p"}).status_code == 415


def test_known_people(hub, make_page, admin_client):
    with hub.db() as con:
        con.execute("INSERT INTO logins(email, at) VALUES('gammel@test.no', 1)")
        con.execute("INSERT INTO logins(email, at) VALUES('admin@test.no', 1)")
    admin_client.post("/api/people/invite", json={"email": "ny@test.no"})
    make_page("p", "people", ["venn@test.no"])
    assert hub.known_people() == ["gammel@test.no", "ny@test.no", "user@test.no", "venn@test.no"]


def test_admin_page_access_buttons_and_people(hub, make_page, admin_client):
    make_page("p", "people", ["venn@test.no"])
    make_page("q", "admin")
    make_page("r")
    admin_client.post("/api/people/invite", json={"email": "ny@test.no"})
    html = admin_client.get("/admin").text
    assert "👥 1 person" in html and "🔒 Bare meg" in html and "🌍 Alle" in html
    assert "toggle-private" not in html and "🌐 delt" not in html
    people = html[html.find('id="people"'):]
    assert "Personer" in people and "ny@test.no" in people and "user@test.no" in people
    assert "admin@test.no" not in people and "Inviter" in people


def test_toggle_private_route_gone(make_page, admin_client):
    make_page("p")
    assert admin_client.post("/api/toggle-private", data={"slug": "p"}).status_code in (404, 405)


def test_admin_page_survives_odd_file_names(hub, make_page, admin_client):
    make_page("p", "people", ["venn@test.no"])
    (hub.ARTIFACTS_DIR / "Timeliste.html").write_text("<body>x</body>")  # scp'd in by hand; not a valid slug
    assert admin_client.get("/admin").status_code == 200
    assert hub.known_people() == ["user@test.no", "venn@test.no"]


def _person_row(html, email):
    people = html[html.find('id="people"'):]
    return people[people.find(email):].split("</li>")[0]


def test_server_config_people_are_not_invited(hub, make_page, admin_client):
    make_page("p")
    admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": ["user@test.no", "ny@test.no"]})
    with hub.db() as con:
        assert hub.access.invited(con) == ["ny@test.no"]
    row = _person_row(admin_client.get("/admin").text, "user@test.no")
    assert "fra serveroppsettet" in row and "Fjern" not in row


def test_server_config_person_invited_earlier_has_no_remove(hub, admin_client):
    admin_client.post("/api/people/invite", json={"email": "user@test.no"})
    row = _person_row(admin_client.get("/admin").text, "user@test.no")
    assert "fra serveroppsettet" in row and "Fjern" not in row
