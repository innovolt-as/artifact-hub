"""Pages ordinary users see, in English (and the nb strings that reach the browser)."""
import json
import re

from tests.conftest import set_pw
from tests.textutil import assert_no_norwegian, visible_text

USER = "user@test.no"
PW = "correct horse"


def test_login_en(client, english):
    body = client.get("/login").text
    assert_no_norwegian(body)
    text = visible_text(body)
    assert "Log in" in text and "@placeholder: you@example.com" in text
    assert "<title>Log in" in body and "Logg" not in body


def test_login_sent_en(client, english):
    body = client.post("/login", data={"email": USER}).text
    assert_no_norwegian(body)
    assert "<strong>user@test.no</strong>" in body
    assert "valid for 15 minutes" in body


def test_login_sent_escapes_email(client, english):
    body = client.post("/login", data={"email": "<b>x</b>@test.no"}).text
    assert "<b>x</b>@" not in body and "&lt;b&gt;x" in body


def test_login_password_en(client, english, pw_mode):
    set_pw(USER, PW)
    body = client.post("/login", data={"email": USER, "password": "wrong"}).text
    assert_no_norwegian(body)
    assert "Wrong e-mail or password" in body
    assert_no_norwegian(client.get("/login").text)


def test_password_pages_en(hub, user_client, client, english, pw_mode):
    body = user_client.get("/password").text
    assert_no_norwegian(body)
    assert "You do not have a password yet" in body

    set_pw(USER, PW)
    body = user_client.get("/password").text
    assert_no_norwegian(body)
    assert "Change password" in body and "at least 10 characters" in body

    for new, msg in (("short1", "at least 10 characters"), ("x" * 201, "too long")):
        body = user_client.post("/password", data={"current": PW, "new1": new, "new2": new}).text
        assert_no_norwegian(body)
        assert msg in visible_text(body)
    body = user_client.post("/password", data={"current": PW, "new1": "longenough1", "new2": "different11"}).text
    assert "do not match" in body
    body = user_client.post("/password", data={"current": PW, "new1": PW, "new2": PW}).text
    assert "different password" in body
    body = user_client.post("/password", data={"current": "nope", "new1": "longenough1", "new2": "longenough1"}).text
    assert_no_norwegian(body)
    assert "Wrong password" in body


def test_password_pending_en(hub, client, english, pw_mode):
    updated = set_pw(USER, PW, must_change=True)
    client.cookies.set(hub.COOKIE, hub.signer.dumps({"email": USER, "pw_change": True, "pw_at": updated}))
    body = client.get("/password").text
    assert_no_norwegian(body)
    assert "Choose a new password" in body and "only be used once" in body


def test_auth_error_en(client, english):
    r = client.get("/auth?token=bad")
    assert r.status_code == 400 and "invalid or has expired" in r.text


def test_home_en(admin_client, english, frozen_monday, make_page):
    make_page("fast", "all", title="Fast app")
    admin_client.get("/")
    body = admin_client.get("/?pw=changed").text
    assert_no_norwegian(body)
    text = visible_text(body)
    assert "Monday 26 October" in text
    assert "Your password has been changed." in text
    empty = visible_text(admin_client.get("/").text)
    assert "Add or remove apps" in empty or "Add apps" in empty


def test_home_empty_en(user_client, english, frozen_monday):
    body = user_client.get("/").text
    assert_no_norwegian(body)
    assert "Add apps" in body


def test_banner_en(admin_client, english, make_page):
    make_page("bannerapp", "all", title="Bannerapp")
    body = admin_client.get("/a/bannerapp/").text
    assert 'aria-label="Back to Artifact Hub"' in body


def _strings(body):
    m = re.search(r'<script type="application/json" id="__hub_strings">(.*?)</script>', body, re.S)
    return json.loads(m.group(1))


def test_home_js_strings_nb(admin_client):
    s = _strings(admin_client.get("/").text)
    assert s["greet"] == ["God natt", "God morgen", "God formiddag", "God ettermiddag", "God kveld"]
    assert s["locale"] == "no-NO"
    assert s["save_failed"] == "Kunne ikke lagre. Prøv igjen."
    assert s["pin"] == "Legg til i favoritter" and s["unpin"] == "Fjern fra favoritter"


def test_home_js_strings_en(admin_client, english):
    s = _strings(admin_client.get("/").text)
    assert s["greet"][1] == "Good morning" and s["locale"] == "en-GB"


def test_front_page_strings_block_is_script_safe(admin_client, monkeypatch):
    from app import i18n
    monkeypatch.setattr(i18n, "js", lambda prefix: {"x": "</script><b>"})
    assert "</script><b>" not in admin_client.get("/").text
