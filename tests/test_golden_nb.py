"""Golden copy of the Norwegian page text. The text must stay word for word the same (HUB_LANG=nb).

Regenerate on purpose with: UPDATE_GOLDEN=1 scripts/test.sh tests/test_golden_nb.py
"""
import os
import time
from pathlib import Path

import pytest

from tests.conftest import set_pw
from tests.textutil import visible_text

GOLDEN = Path(__file__).parent / "golden" / "nb"
USER, ADMIN, FRIEND = "user@test.no", "admin@test.no", "venn@test.no"
PW = "riktig passord"


def _ok(r):
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return r.text


def login(client, **_):
    return _ok(client.get("/login"))


def login_sent(client, **_):
    return _ok(client.post("/login", data={"email": USER}))


def login_password(client, pw_mode, **_):
    return _ok(client.get("/login"))


def login_password_error(client, pw_mode, **_):
    set_pw(USER, PW)
    return _ok(client.post("/login", data={"email": USER, "password": "feil"}))


def password_change(hub, user_client, pw_mode, **_):
    set_pw(USER, PW)
    return _ok(user_client.get("/password"))


def password_no_password(user_client, pw_mode, **_):
    return _ok(user_client.get("/password"))


def password_error(hub, user_client, pw_mode, **_):
    set_pw(USER, PW)
    return _ok(user_client.post("/password", data={"current": PW, "new1": "kort1", "new2": "kort1"}))


def home_empty(user_client, **_):
    return _ok(user_client.get("/"))


def home_apps(hub, admin_client, upload, make_page, **_):
    _ok(admin_client.get("/"))  # first visit: the admin gets the apps that exist
    make_page("fast", "all", title="Fast app")
    make_page("hemmelig", "admin", title="Hemmelig app")
    make_page("ny", "all", title="Ny app")
    r = admin_client.post("/api/link", data={"title": "Ekstern lenke", "url": "https://example.com"})
    assert r.status_code == 200, r.text
    with hub.db() as con:
        hub.home.set_added(con, ADMIN, "fast", True)
        hub.home.set_added(con, ADMIN, "hemmelig", True)
        hub.home.set_added(con, ADMIN, "ekstern-lenke", True)
        hub.home.set_added(con, ADMIN, "ny", False)
        hub.home._put(con, ADMIN, "seen", ["fast", "hemmelig", "ekstern-lenke"])
        hub.home.set_pin(con, ADMIN, "fast", True)
        hub.home.set_view(con, ADMIN, "cards")
    return _ok(admin_client.get("/"))


def home_notice(user_client, **_):
    return _ok(user_client.get("/?pw=changed"))


def _admin_setup(hub, admin_client, make_page):
    make_page("alle", "all", title="For alle")
    make_page("folk", "people", [FRIEND], title="For noen")
    make_page("admin-app", "admin", title="Bare admin")
    r = admin_client.post("/api/people/invite", json={"email": "ny@test.no", "password": "midlertidig-pw"})
    assert r.status_code == 200, r.text


def admin(hub, admin_client, make_page, **_):
    _admin_setup(hub, admin_client, make_page)
    return _ok(admin_client.get("/admin"))


def admin_password(hub, admin_client, make_page, pw_mode, **_):
    _admin_setup(hub, admin_client, make_page)
    set_pw(USER, PW)
    set_pw(FRIEND, PW, must_change=True)
    return _ok(admin_client.get("/admin"))


def settings(user_client, **_):
    return _ok(user_client.get("/settings"))


def settings_password(user_client, pw_mode, **_):
    return _ok(user_client.get("/settings"))


def stats(hub, admin_client, make_page, **_):
    make_page("a", "all", title="App A")
    make_page("ubrukt", "all", title="Ubrukt")
    with hub.db() as con:
        hub.home.record_visit(con, USER, "a", now=int(time.time()) - 300)
    return _ok(admin_client.get("/admin/stats"))


def consent(admin_client, pending_req, **_):
    return _ok(admin_client.get(f"/oauth/consent?req={pending_req}"))


def consent_error(user_client, pending_req, **_):
    r = user_client.get(f"/oauth/consent?req={pending_req}")
    assert r.status_code == 403
    return r.text


def app_banner(admin_client, make_page, **_):
    make_page("bannerapp", "all", title="Bannerapp")
    return _ok(admin_client.get("/a/bannerapp/"))


def auth_error(client, **_):
    r = client.get("/auth?token=bad")
    assert r.status_code == 400
    return r.text


CASES = {f.__name__: f for f in (
    login, login_sent, login_password, login_password_error, password_change, password_no_password,
    password_error, home_empty, home_apps, home_notice, admin, admin_password, settings, settings_password, stats, consent,
    consent_error, app_banner, auth_error)}
JSON_CASES = {"auth_error"}


@pytest.mark.parametrize("name", list(CASES))
def test_nb_text_unchanged(name, request, frozen_monday, hub):
    fn = CASES[name]
    wanted = [p for p in fn.__code__.co_varnames[:fn.__code__.co_argcount]]
    args = {p: request.getfixturevalue(p) for p in wanted}
    body = fn(**args)
    text = body if name in JSON_CASES else visible_text(body)
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert text == path.read_text()
