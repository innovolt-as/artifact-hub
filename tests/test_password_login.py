# tests/test_password_login.py
import time
from tests.conftest import set_pw


def _login(client, email, password, next="/"):
    return client.post("/login", data={"email": email, "password": password, "next": next})


def test_login_page_shows_password_form(pw_mode, client):
    html = client.get("/login").text
    assert 'name="password"' in html and "magisk" not in html.lower()


def test_correct_password_logs_in(pw_mode, hub, client):
    set_pw("user@test.no", "passord123")
    r = _login(client, "User@Test.no", "passord123", next="/admin")
    assert r.status_code == 302 and r.headers["location"] == "/admin"
    assert client.get("/").status_code == 200
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM logins WHERE email='user@test.no'").fetchone()[0] == 1


def test_four_failures_look_the_same(pw_mode, hub, client):
    set_pw("user@test.no", "passord123")           # allowed, has password: wrong password
    set_pw("venn@test.no", "passord123")           # has password but is NOT allowed
    bodies = set()
    for email, pw in [("user@test.no", "feil"), ("venn@test.no", "passord123"),
                      ("admin@test.no", "passord123"),            # allowed, no password row
                      ("fremmed@x.no", "passord123")]:            # unknown
        r = _login(client, email, pw)
        assert r.status_code == 200 and "Feil e-post eller passord" in r.text
        assert hub.COOKIE not in r.cookies
        bodies.add(r.text.replace(email, "E"))
    assert len(bodies) == 1
    for email in ("user@test.no", "venn@test.no", "admin@test.no", "fremmed@x.no"):
        assert len(hub._pw_fails[f"e:{email}"]) == 1
    assert len(hub._pw_fails["ip:testclient"]) == 4
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM magic_tokens").fetchone()[0] == 0


def test_missing_password_field_is_not_magic_link(pw_mode, hub, client):
    r = client.post("/login", data={"email": "user@test.no"})
    assert r.status_code == 200 and "Feil e-post eller passord" in r.text
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM magic_tokens").fetchone()[0] == 0


def test_auth_is_404_in_password_mode(pw_mode, hub, client):
    import hashlib, secrets
    tok = secrets.token_urlsafe(16)
    with hub.db() as con:
        con.execute("INSERT INTO magic_tokens(token_hash,email,expires_at) VALUES(?,?,?)",
                    (hashlib.sha256(tok.encode()).hexdigest(), "user@test.no", int(time.time()) + 600))
    assert client.get(f"/auth?token={tok}").status_code == 404


def test_temporary_password_gives_pending_cookie_only(pw_mode, hub, client):
    set_pw("user@test.no", "temp-passord", must_change=True)
    r = _login(client, "user@test.no", "temp-passord", next="/a/x/")
    assert r.status_code == 302
    assert r.headers["location"] == "/password?next=%2Fa%2Fx%2F"
    assert client.get("/").status_code == 302 and client.get("/").headers["location"] == "/login"
    assert client.get("/api/me").status_code == 401
    with hub.db() as con:
        assert con.execute("SELECT COUNT(*) FROM logins").fetchone()[0] == 0
    # the cookie carries the pending flag
    raw = client.cookies.get(hub.COOKIE)
    assert "pw_change" in hub.signer.loads(raw)


def test_rate_limit_per_email(pw_mode, hub, client, monkeypatch):
    set_pw("user@test.no", "passord123")
    for _ in range(hub.MAX_PW_FAILS_PER_EMAIL):
        _login(client, "user@test.no", "feil")
    calls = []
    monkeypatch.setattr(hub.passwd, "verify_password", lambda p, h: calls.append(1) or True)
    r = _login(client, "user@test.no", "passord123")
    assert r.status_code == 200 and "Feil e-post eller passord" in r.text and calls == []


def test_success_clears_counter(pw_mode, hub, client):
    set_pw("user@test.no", "passord123")
    for _ in range(hub.MAX_PW_FAILS_PER_EMAIL - 1):
        _login(client, "user@test.no", "feil")
    assert _login(client, "user@test.no", "passord123").status_code == 302
    assert "e:user@test.no" not in hub._pw_fails


def test_default_mode_untouched(hub, client):
    html = client.get("/login").text
    assert 'name="password"' not in html
    r = client.post("/login", data={"email": "user@test.no"})
    assert r.status_code == 200 and "Sjekk e-posten" in r.text


class _Req:
    def __init__(self, cookies):
        self.cookies = cookies


def test_pending_helper_and_current_user(pw_mode, hub, client):
    at = set_pw("user@test.no", "temp-passord", must_change=True)
    _login(client, "user@test.no", "temp-passord")
    req = _Req({hub.COOKIE: client.cookies.get(hub.COOKIE)})
    assert hub.pending_password_user(req) == ("user@test.no", at)
    assert hub.current_user(req) is None
    full = _Req({hub.COOKIE: hub.signer.dumps({"email": "user@test.no"})})
    assert hub.pending_password_user(full) is None
    assert hub.current_user(full) == "user@test.no"


def test_ip_lockout_across_emails(pw_mode, hub, client, monkeypatch):
    set_pw("user@test.no", "passord123")
    for i in range(hub.MAX_PW_FAILS_PER_IP):
        _login(client, f"x{i}@x.no", "feil")
    calls = []
    monkeypatch.setattr(hub.passwd, "verify_password", lambda p, h: calls.append(1) or True)
    r = _login(client, "user@test.no", "passord123")
    assert r.status_code == 200 and "Feil e-post eller passord" in r.text and calls == []


def test_email_window_is_15_minutes(pw_mode, hub):
    import time
    old = time.time() - 16 * 60
    hub._pw_fails["e:a@x.no"] = [old] * hub.MAX_PW_FAILS_PER_EMAIL
    hub._pw_fails["ip:1.2.3.4"] = [old] * hub.MAX_PW_FAILS_PER_IP
    assert hub.pw_rate_limited("b@x.no", "1.2.3.4") is True      # IP window is an hour
    assert hub.pw_rate_limited("a@x.no", "9.9.9.9") is False     # e-mail window has passed
    assert "e:a@x.no" not in hub._pw_fails


def test_missing_row_verifies_dummy_hash(pw_mode, hub, client, monkeypatch):
    calls = []
    monkeypatch.setattr(hub.passwd, "verify_password", lambda p, h: calls.append(h) or False)
    _login(client, "admin@test.no", "x")
    assert calls == [hub.passwd.DUMMY_HASH]


def test_reset_lifts_email_lockout(pw_mode, hub, client):
    set_pw("user@test.no", "passord123")
    for _ in range(hub.MAX_PW_FAILS_PER_EMAIL):
        _login(client, "user@test.no", "feil")
    assert _login(client, "user@test.no", "passord123").status_code == 200  # locked out
    # updated_at has second resolution: age the failures so the reset is clearly after them
    hub._pw_fails["e:user@test.no"] = [t - 5 for t in hub._pw_fails["e:user@test.no"]]
    set_pw("user@test.no", "passord123")  # CLI/admin reset bumps updated_at
    assert _login(client, "user@test.no", "passord123").status_code == 302


def test_overlong_password_is_wrong_without_hashing(pw_mode, hub, client, monkeypatch):
    set_pw("user@test.no", "passord123")
    calls = []
    monkeypatch.setattr(hub.passwd, "verify_password", lambda p, h: calls.append(1) or True)
    r = _login(client, "user@test.no", "a" * 1025)
    assert r.status_code == 200 and "Feil e-post eller passord" in r.text and calls == []


def test_empty_login_mode_means_default(monkeypatch):
    import importlib
    import app.main as m
    monkeypatch.setenv("LOGIN_MODE", "")
    try:
        importlib.reload(m)
        assert m.LOGIN_MODE == "magic-link"
    finally:
        monkeypatch.delenv("LOGIN_MODE")
        importlib.reload(m)


def test_pending_user_cannot_open_consent(pw_mode, hub, client, pending_req):
    set_pw("user@test.no", "temp-passord", must_change=True)
    _login(client, "user@test.no", "temp-passord")
    r = client.get(f"/oauth/consent?req={pending_req}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?next=")
