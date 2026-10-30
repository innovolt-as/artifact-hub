"""The code lock on /a/{slug}/: the gate, the code screen, /lock/{slug} and the unlock cookie."""
import io
import json
import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app import applock, home, i18n, main
from tests.conftest import lock, make_client, unlock

USER, ADMIN = "user@test.no", "admin@test.no"
MARKER = "marker-only-the-app-has"
HUB_JS = re.compile(r'<script src="/static/hub\.js"[^>]* data-lock="1"')


@pytest.fixture
def page(hub):
    """page(slug): a page for everyone, with a marker in its body, because the screen prints the slug too."""
    def _make(slug):
        hub.save_page(slug, f"<!doctype html><html><head><title>t</title></head><body>{MARKER}</body></html>",
                      create=True, private=False, title=f"App {slug}")
    return _make


@pytest.fixture
def locked(page):
    """The page notat, locked for USER with the code 1234."""
    page("notat")
    lock(USER, "notat")


@pytest.fixture
def folder(admin_client, upload):
    """The folder app notat, locked for ADMIN with the code 1234."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", f"<html><body>{MARKER}</body></html>")
        z.writestr("sub/page.html", f"<html><body>{MARKER}</body></html>")
        z.writestr("data.json", f'{{"x": "{MARKER}"}}')
        z.writestr("logo.png", MARKER)
    upload(admin_client, "notat.zip", buf.getvalue(), title="Mappe")  # the title makes the meta.json
    lock(ADMIN, "notat")


def _cookie(r) -> str:
    """The value in a response's Set-Cookie, to copy by hand."""
    return r.headers["set-cookie"].split(";")[0].split("=", 1)[1]


def _next_code(code: str) -> str:
    """A valid code that is not `code`; applock.reset picks at random."""
    return f"{(int(code) + 1) % 10_000:04d}"


def _one_time(hub) -> str:
    lock(USER, "notat")
    with hub.db() as con:
        return applock.reset(con, USER)


def _new_code(client, code, new1, new2):
    return client.post("/lock/notat", data={"code": code, "next": "/a/notat/", "new1": new1, "new2": new2})


# ---------------------------------------------------------------- the gate
def test_a_locked_page_shows_the_code_screen(user_client, locked):
    r = user_client.get("/a/notat/")
    assert r.status_code == 423
    assert r.headers["cache-control"] == "no-store"
    assert 'name="code"' in r.text and "App notat" in r.text
    assert MARKER not in r.text
    assert i18n.t("lock.back") in r.text
    assert '<script src="/static/lock.js" defer></script>' in r.text


def test_the_code_field_has_the_right_keyboard_and_no_keychain(user_client, locked):
    field = re.search(r'<input[^>]*name="code"[^>]*>', user_client.get("/a/notat/").text).group(0)
    for attr in ('type="text"', 'class="code"', 'inputmode="numeric"', 'pattern="[0-9]*"', 'maxlength="4"',
                 'autocomplete="off"', "autofocus"):
        assert attr in field


def test_lock_js_sends_the_form_once(client):
    js = client.get("/static/lock.js").text
    assert 'querySelector("button").click()' in js and "form.requestSubmit" not in js and "preventDefault" in js


def test_the_screen_stays_on_the_address_it_was_shown_for(user_client, locked):
    assert 'name="next" value="/a/notat/?x=1"' in user_client.get("/a/notat/?x=1").text


def test_a_locked_page_is_not_counted_as_a_visit(hub, user_client, locked):
    user_client.get("/a/notat/")
    with hub.db() as con:
        assert "notat" not in home.visit_stats(con, USER)


@pytest.mark.parametrize("dest", ["empty", "image", "script", "iframe"])
def test_other_requests_get_423_without_content(user_client, locked, dest):
    r = user_client.get("/a/notat/", headers={"sec-fetch-dest": dest})
    assert r.status_code == 423
    assert r.headers["cache-control"] == "no-store"
    assert MARKER not in r.text and 'name="code"' not in r.text


@pytest.mark.parametrize("path", ["", "sub/page.html", "data.json", "logo.png"])
def test_folder_app_stays_shut(admin_client, folder, path):
    r = admin_client.get(f"/a/notat/{path}", headers={"sec-fetch-dest": "empty"})
    assert r.status_code == 423 and MARKER not in r.text
    r = admin_client.get(f"/a/notat/{path}")
    assert r.status_code == 423 and 'name="code"' in r.text and MARKER not in r.text


def test_folder_meta_json_is_still_hidden_when_unlocked(hub, admin_client, folder):
    assert (hub.ARTIFACTS_DIR / "notat" / "meta.json").is_file()
    unlock(admin_client, "notat")
    assert admin_client.get("/a/notat/meta.json").status_code == 404


def test_unknown_or_hidden_app_is_404_before_the_lock(user_client, make_page):
    lock(USER, "finnes-ikke")
    assert user_client.get("/a/finnes-ikke/").status_code == 404
    make_page("x", "admin")
    lock(USER, "x")
    assert user_client.get("/a/x/").status_code == 404


def test_other_users_and_apps_notice_nothing(admin_client, user_client, page):
    page("notat")
    page("annet")
    requests = ((admin_client, "/a/notat/"), (user_client, "/a/annet/"))
    before = [c.get(url) for c, url in requests]
    lock(USER, "notat")
    for old, (c, url) in zip(before, requests, strict=True):
        new = c.get(url)
        assert new.status_code == 200 and "data-lock" not in new.text
        assert new.text == old.text and new.headers == old.headers


def test_the_right_code_opens_the_app(hub, user_client, locked):
    r = unlock(user_client, "notat")
    assert r.status_code == 303 and r.headers["location"] == "/a/notat/"
    assert r.headers["cache-control"] == "no-store"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("hub_unlock_notat=")
    for part in ("HttpOnly", "Max-Age=600", "SameSite=lax", "Secure", "Path=/"):
        assert part in cookie
    r = user_client.get("/a/notat/")
    assert r.status_code == 200 and MARKER in r.text and HUB_JS.search(r.text)
    with hub.db() as con:
        assert "notat" in home.visit_stats(con, USER)


def test_folder_pages_of_a_locked_app_have_the_mark(admin_client, folder):
    unlock(admin_client, "notat")
    assert HUB_JS.search(admin_client.get("/a/notat/sub/page.html").text)


def test_folder_files_of_a_locked_app_are_not_stored(hub, admin_client, folder):
    unlock(admin_client, "notat")
    r = admin_client.get("/a/notat/data.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    with hub.db() as con:
        applock.set_locked(con, ADMIN, "notat", False)
    assert "cache-control" not in admin_client.get("/a/notat/data.json").headers


# ---------------------------------------------------------------- wrong codes
def test_a_wrong_code_shows_the_screen_again(user_client, locked):
    r = unlock(user_client, "notat", "0000")
    assert r.status_code == 423 and r.headers["cache-control"] == "no-store"
    assert i18n.t("lock.err.wrong") in r.text and 'name="code"' in r.text
    assert "set-cookie" not in r.headers
    assert user_client.get("/a/notat/").status_code == 423


def test_a_blocked_user_sees_the_wait(user_client, locked):
    for _ in range(5):
        r = unlock(user_client, "notat", "0000")
    wait = i18n.t("lock.err.blocked", minutes=15)
    assert r.status_code == 423 and wait in r.text
    r = unlock(user_client, "notat")
    assert r.status_code == 423 and wait in r.text and "set-cookie" not in r.headers


# ---------------------------------------------------------------- the unlock cookie
def test_the_unlock_is_tied_to_user_app_and_code(hub, page):
    page("notat")
    page("annet")
    lock(USER, "notat")
    lock(USER, "annet")
    lock(ADMIN, "notat")
    owner = make_client(USER)
    value = _cookie(unlock(owner, "notat"))
    assert owner.get("/a/notat/").status_code == 200

    someone_else = make_client(ADMIN)
    someone_else.cookies.set("hub_unlock_notat", value)
    assert someone_else.get("/a/notat/").status_code == 423

    other_name = make_client(USER)
    other_name.cookies.set("hub_unlock_annet", value)
    assert other_name.get("/a/annet/").status_code == 423

    with hub.db() as con:
        applock.set_code(con, USER, "4321")
    assert owner.get("/a/notat/").status_code == 423


def test_the_unlock_runs_out(user_client, locked, monkeypatch):
    value = _cookie(unlock(user_client, "notat"))
    copied = make_client(USER)  # set by hand: the client's own jar would drop a cookie past its Max-Age
    copied.cookies.set("hub_unlock_notat", value)
    assert copied.get("/a/notat/").status_code == 200
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 601)
    assert copied.get("/a/notat/").status_code == 423


def test_a_session_signed_cookie_is_not_an_unlock(hub, user_client, locked):
    with hub.db() as con:
        payload = {"email": USER, "slug": "notat", "at": applock.get(con, USER)["updated_at"]}
    user_client.cookies.set("hub_unlock_notat", hub.signer.dumps(payload))
    assert user_client.get("/a/notat/").status_code == 423
    user_client.cookies.set("hub_unlock_notat", hub.unlock_signer.dumps(payload))
    assert user_client.get("/a/notat/").status_code == 200


def test_logout_clears_the_unlocks(user_client, locked):
    unlock(user_client, "notat")
    r = user_client.post("/logout")
    deleted = [c for c in r.headers.get_list("set-cookie") if c.startswith("hub_unlock_notat=")]
    assert len(deleted) == 1 and "Max-Age=0" in deleted[0]


def test_logout_survives_a_cookie_name_it_cannot_answer(user_client, locked):
    unlock(user_client, "notat")
    r = user_client.post("/logout", headers={"Cookie": "hub_unlock_x y=1; hub_unlock_notat=zz"})
    assert r.status_code in (302, 303)
    assert any(c.startswith("hub_unlock_notat=") for c in r.headers.get_list("set-cookie"))


# ---------------------------------------------------------------- /lock/{slug}
@pytest.mark.parametrize("target, location", [
    ("/a/notat/sub/page.html?x=1", "/a/notat/sub/page.html?x=1"),
    ("/a/notat/?p=../x", "/a/notat/?p=../x"),
    ("/a/notat/../admin", "/a/notat/"),
    ("/a/notat/%2e%2e/admin", "/a/notat/"),
    ("/a/notat/.%2E/admin", "/a/notat/"),
    ("/a/notat/x/..%2f..%2f..%2fadmin", "/a/notat/"),
    ("/a/notat\\..\\admin", "/a/notat/"),
    ("//evil.example", "/a/notat/"),
    ("/a/notat2/", "/a/notat/"),
    ("/admin", "/a/notat/"),
    ("", "/a/notat/"),
])
def test_next_stays_in_the_app(user_client, locked, target, location):
    r = user_client.post("/lock/notat", data={"code": "1234", "next": target})
    assert r.status_code == 303 and r.headers["location"] == location


def test_a_wrong_code_keeps_a_good_next_and_drops_a_bad_one(user_client, locked):
    good = user_client.post("/lock/notat", data={"code": "0000", "next": "/a/notat/sub/?x=1"})
    assert 'name="next" value="/a/notat/sub/?x=1"' in good.text
    bad = user_client.post("/lock/notat", data={"code": "0000", "next": "//evil.example"})
    assert 'name="next" value="/a/notat/"' in bad.text


def test_get_of_the_lock_url_goes_to_the_app(client, user_client, locked):
    r = user_client.get("/lock/notat")
    assert r.status_code == 302 and r.headers["location"] == "/a/notat/"
    assert client.get("/lock/notat").headers["location"].startswith("/login")


def test_post_to_an_app_without_a_lock_checks_nothing(hub, user_client, locked, page):
    page("annet")
    r = user_client.post("/lock/annet", data={"code": "0000", "next": "/a/annet/x"})
    assert r.status_code == 303 and r.headers["location"] == "/a/annet/x"
    assert "set-cookie" not in r.headers
    with hub.db() as con:
        assert applock.get(con, USER)["fails"] == 0


def test_post_to_an_unknown_app_is_404(user_client, make_page):
    lock(USER, "finnes-ikke")
    assert unlock(user_client, "finnes-ikke").status_code == 404
    make_page("x", "admin")
    lock(USER, "x")
    assert unlock(user_client, "x").status_code == 404


def test_a_capitalised_session_is_still_locked(page):
    page("notat")
    lock(ADMIN, "notat")
    capitalised = make_client("Admin@Test.no")
    assert capitalised.get("/a/notat/").status_code == 423
    assert unlock(capitalised, "notat").status_code == 303
    assert capitalised.get("/a/notat/").status_code == 200


def test_a_slug_with_dot_and_underscore_round_trips(user_client, page):
    page("my.app_1")
    lock(USER, "my.app_1")
    assert user_client.get("/a/my.app_1/").status_code == 423
    assert unlock(user_client, "my.app_1").status_code == 303
    assert user_client.get("/a/my.app_1/").status_code == 200


# ---------------------------------------------------------------- the one-time code
def test_one_time_code_asks_for_a_new_code(hub, user_client, page):
    page("notat")
    r = unlock(user_client, "notat", _one_time(hub))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert 'name="new1"' in r.text and 'name="new2"' in r.text
    assert "set-cookie" not in r.headers
    with hub.db() as con:
        assert applock.get(con, USER)["must_change"] == 1
    assert user_client.get("/a/notat/").status_code == 423


def test_new_code_must_be_four_digits_twice(hub, user_client, page):
    page("notat")
    code = _one_time(hub)
    good, other = _next_code(code), _next_code(_next_code(code))
    for new1, new2, key in (("123", "123", "lock.err.format"), ("12a4", "12a4", "lock.err.format"),
                            (good, other, "lock.err.mismatch"), (code, code, "lock.err.same")):
        r = _new_code(user_client, code, new1, new2)
        assert r.status_code == 200 and i18n.t(key) in r.text
        assert f'name="code" value="{code}"' in r.text and 'name="new1"' in r.text
        assert "set-cookie" not in r.headers
    with hub.db() as con:
        assert applock.get(con, USER)["must_change"] == 1


def test_new_code_opens_the_app(hub, user_client, page):
    page("notat")
    code = _one_time(hub)
    new = _next_code(code)
    r = _new_code(user_client, code, new, new)
    assert r.status_code == 303 and r.headers["location"] == "/a/notat/"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["set-cookie"].startswith("hub_unlock_notat=")
    assert user_client.get("/a/notat/").status_code == 200
    with hub.db() as con:
        assert applock.get(con, USER)["must_change"] == 0
    other_device = make_client(USER)
    assert unlock(other_device, "notat", code).status_code == 423
    assert unlock(other_device, "notat", new).status_code == 303


# ---------------------------------------------------------------- the data routes
GATED = {
    ("GET", "/api/store/{slug}"),
    ("GET", "/api/store/{slug}/c"), ("GET", "/api/store/{slug}/d"),
    ("PUT", "/api/store/{slug}/d"), ("DELETE", "/api/store/{slug}/d"),
    ("GET", "/api/data/{app_name}"), ("POST", "/api/data/{app_name}/_batch"),
    ("GET", "/api/data/{app_name}/{key:path}"), ("PUT", "/api/data/{app_name}/{key:path}"),
    ("DELETE", "/api/data/{app_name}/{key:path}"),
    ("GET", "/a/{slug}/{path:path}"),
}
EXEMPT = {("GET", "/a/{slug}")}  # the bare redirect
SECRET = {"note": "Secret"}


def _fill(method, template):
    """(method, url, kwargs) for a route, with example values for notat."""
    url = (template.replace("{slug}", "notat").replace("{app_name}", "notat")
           .replace("{key:path}", "k").replace("{path:path}", "index.html"))
    if url.endswith("/c"):
        url += "?path=a"
    elif url.endswith("/d"):
        url += "?path=a/b"
    kwargs = {"headers": {"content-type": "application/json"}}
    if method == "PUT":
        kwargs["content"] = '{"value": "x"}' if "/api/data/" in url else '{"note": "new"}'
    elif method == "POST":
        kwargs["content"] = '{"set": {"k2": "x"}}'
    return method, url, kwargs


def _rows(hub):
    with hub.db() as con:
        return ([tuple(r) for r in con.execute("SELECT * FROM docs ORDER BY 1,2,3,4")],
                [tuple(r) for r in con.execute("SELECT * FROM app_data ORDER BY 1,2,3")])


@pytest.fixture
def stored(hub, locked):
    """Locked notat with a document and a key/value row that both say Secret."""
    hub.doc_set("notat", USER, "a/b", SECRET)
    with hub.db() as con:
        con.execute("INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?)",
                    (USER, "notat", "k", '"Secret"', 1))


def test_every_route_is_in_the_table(hub):
    seen = {(m, r.path) for r in hub.app.routes if isinstance(r, APIRoute)
            and r.path.startswith(("/a/", "/api/store/", "/api/data/")) for m in r.methods - {"HEAD"}}
    assert seen == GATED | EXEMPT


@pytest.mark.parametrize("method, template", sorted(GATED))
def test_every_gated_route_refuses(hub, user_client, stored, method, template):
    before = _rows(hub)
    method, url, kwargs = _fill(method, template)
    r = user_client.request(method, url, **kwargs)
    assert r.status_code == 423 and r.headers["cache-control"] == "no-store"
    assert "Secret" not in r.text
    assert _rows(hub) == before


@pytest.mark.parametrize("method, template", sorted(GATED))
def test_every_gated_route_opens_after_unlock(user_client, stored, method, template):
    unlock(user_client, "notat")
    method, url, kwargs = _fill(method, template)
    assert user_client.request(method, url, **kwargs).status_code != 423


def test_other_users_data_routes_notice_nothing(hub, admin_client, page):
    page("notat")
    lock(USER, "notat")
    hub.doc_set("notat", ADMIN, "a/b", SECRET)
    assert admin_client.get("/api/store/notat/d?path=a/b").json() == {"data": SECRET}
    assert admin_client.put("/api/data/notat/k", json={"value": 1}).status_code == 200
    assert admin_client.get("/api/data/notat/k").json()["value"] == 1


def test_a_write_behind_the_lock_is_not_saved(hub, user_client, locked):
    r = user_client.put("/api/store/notat/d?path=a/b", json=SECRET)
    assert r.status_code == 423
    assert hub.doc_get("notat", USER, "a/b") is None


def test_polling_does_not_renew_the_lock(user_client, locked):
    unlock(user_client, "notat")
    r = user_client.get("/api/store/notat/c?path=a")
    assert r.status_code == 200 and "set-cookie" not in r.headers


# ---------------------------------------------------------------- the ping and the heartbeat

def _at(monkeypatch, seconds, _start=time.time):
    """Move the clock to `seconds` from now; a second call counts from the real now again, not from the first."""
    now = _start()
    monkeypatch.setattr(time, "time", lambda: now + seconds)


def _with_cookie(value):
    """A client with the unlock set by hand: the client's own jar would drop a cookie past its Max-Age."""
    c = make_client(USER)
    c.cookies.set("hub_unlock_notat", value)
    return c


def test_ping_renews_a_valid_unlock(user_client, locked, monkeypatch):
    first = _cookie(unlock(user_client, "notat"))
    _at(monkeypatch, 300)
    r = _with_cookie(first).post("/api/lock/notat/ping")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["cache-control"] == "no-store"
    renewed = _cookie(r)
    _at(monkeypatch, 601)
    assert _with_cookie(renewed).get("/a/notat/").status_code == 200
    assert _with_cookie(first).get("/a/notat/").status_code == 423


def test_ping_cannot_revive_an_expired_unlock(user_client, locked, monkeypatch):
    value = _cookie(unlock(user_client, "notat"))
    _at(monkeypatch, 601)
    r = _with_cookie(value).post("/api/lock/notat/ping")
    assert r.status_code == 423 and "set-cookie" not in r.headers
    assert r.headers["cache-control"] == "no-store"


def test_ping_without_an_unlock_is_423(user_client, locked):
    r = user_client.post("/api/lock/notat/ping")
    assert r.status_code == 423 and "set-cookie" not in r.headers


def test_ping_after_the_lock_is_off_sets_nothing(user_client, locked):
    with main.db() as con:
        applock.set_locked(con, USER, "notat", False)
    for slug in ("notat", "no-such-app"):
        r = user_client.post(f"/api/lock/{slug}/ping")
        assert r.status_code == 200 and r.json() == {"ok": True} and "set-cookie" not in r.headers


def test_ping_logged_out_is_401(client, locked):
    assert client.post("/api/lock/notat/ping").status_code == 401


def test_the_page_of_an_unlocked_app_carries_data_lock(user_client, locked):
    unlock(user_client, "notat")
    assert HUB_JS.search(user_client.get("/a/notat/").text)


def test_a_page_with_no_lock_has_no_data_lock(user_client, page):
    page("fri")
    html = user_client.get("/a/fri/").text
    assert "/static/hub.js" in html and "data-lock" not in html


def test_hub_js_handles_423_and_pings(client):
    js = client.get("/static/hub.js").text
    for needle in ("r.status === 423", "/ping", "visibilitychange", "pageshow"):
        assert needle in js


def test_the_lock_string_reaches_hub_js():
    for lang in ("nb", "en"):
        assert "js.hub.locked" in json.loads(Path(f"app/lang/{lang}.json").read_text())
