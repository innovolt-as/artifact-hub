"""A session ends when its person may no longer log in, and when it is cut short (password changed or reset)."""
from tests.conftest import make_client, set_pw

FRIEND = "venn@ute.no"


def test_removed_person_is_out_at_once(hub, admin_client, make_page):
    make_page("p")
    c = make_client(FRIEND)
    assert c.get("/a/p/").status_code == 200
    assert admin_client.post("/api/people/remove", json={"email": FRIEND}).status_code == 200
    r = c.get("/a/p/")
    assert r.status_code == 302 and r.headers["location"].startswith("/login")
    assert c.get("/api/me").status_code == 401
    # invited again: the old cookie stays dead
    assert admin_client.post("/api/people/invite", json={"email": FRIEND}).status_code == 200
    assert c.get("/api/me").status_code == 401
    assert make_client(FRIEND).get("/api/me").status_code == 401  # a cookie without the new number
    fresh = make_client()
    resp = hub.RedirectResponse("/")
    hub.set_session(resp, FRIEND)
    fresh.cookies.set(hub.COOKIE, resp.headers["set-cookie"].split(";")[0].split("=", 1)[1])
    assert fresh.get("/api/me").status_code == 200


def test_login_link_sent_before_removal_is_dead(hub, admin_client, client, monkeypatch):
    with hub.db() as con:
        hub.access.invite(con, FRIEND)
    links = []
    monkeypatch.setattr(hub, "send_magic_link", lambda email, link: links.append(link))
    client.post("/login", data={"email": FRIEND})
    assert admin_client.post("/api/people/remove", json={"email": FRIEND}).status_code == 200
    assert client.get(links[0].replace(hub.BASE_URL, "")).status_code == 400


def test_old_cookies_keep_working_after_the_upgrade(hub, user_client):
    assert "n" not in hub.signer.loads(user_client.cookies.get(hub.COOKIE))  # as set before there were numbers
    assert user_client.get("/api/me").status_code == 200


def test_password_change_logs_out_other_devices(pw_mode, hub, user_client):
    set_pw("user@test.no", "passord123")
    other = make_client("user@test.no")
    r = user_client.post("/password", data={"current": "passord123", "new1": "nytt-passord-1", "new2": "nytt-passord-1"})
    assert r.status_code == 302
    assert other.get("/api/me").status_code == 401
    assert user_client.get("/api/me").status_code == 200  # this device got a new cookie


def test_admin_reset_logs_the_person_out(pw_mode, hub, admin_client, user_client):
    set_pw("user@test.no", "passord123")
    assert admin_client.post("/api/people/password", json={"email": "user@test.no", "password": "midlertidig-1"}).status_code == 200
    assert user_client.get("/api/me").status_code == 401
