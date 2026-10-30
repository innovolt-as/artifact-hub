"""Connecting a new Claude asks for the code when the admin has one."""
import pytest

from app import applock, i18n, main
from tests.conftest import lock, make_client, unlock

ADMIN = "admin@test.no"


def _post(client, req, code=None, decision="allow"):
    data = {"req": req, "decision": decision}
    if code is not None:
        data["code"] = code
    return client.post("/oauth/consent", data=data)


def _requests() -> int:
    with main.db() as con:
        return con.execute("SELECT COUNT(*) FROM oauth_requests").fetchone()[0]


@pytest.fixture
def locked(hub):
    hub.save_page("notat", "<!doctype html><html><head><title>t</title></head><body>x</body></html>",
                  create=True, private=False, title="Notat")
    lock(ADMIN, "notat")


def test_without_a_code_the_page_is_as_before(admin_client, pending_req):
    assert 'name="code"' not in admin_client.get("/oauth/consent", params={"req": pending_req}).text
    r = _post(admin_client, pending_req)
    assert r.status_code == 303 and "code=" in r.headers["location"]


def test_with_a_code_the_page_asks_for_it(admin_client, pending_req, locked):
    t = admin_client.get("/oauth/consent", params={"req": pending_req}).text
    assert 'name="code"' in t and 'inputmode="numeric"' in t


def test_the_right_code_gives_access(admin_client, pending_req, locked):
    r = _post(admin_client, pending_req, "1234")
    assert r.status_code == 303 and "code=" in r.headers["location"]


def test_a_wrong_code_shows_the_page_again_and_keeps_the_request(admin_client, pending_req, locked):
    r = _post(admin_client, pending_req, "0000")
    assert r.status_code == 403 and 'name="code"' in r.text and i18n.t("lock.err.wrong") in r.text
    assert _requests() == 1
    r = _post(admin_client, pending_req, "1234")
    assert r.status_code == 303 and "code=" in r.headers["location"]


def test_a_missing_code_is_wrong(admin_client, pending_req, locked):
    r = _post(admin_client, pending_req)
    assert r.status_code == 403 and i18n.t("lock.err.wrong") in r.text
    assert _requests() == 1


def test_deny_needs_no_code(admin_client, pending_req, locked):
    r = _post(admin_client, pending_req, decision="deny")
    assert r.status_code == 303 and "error=access_denied" in r.headers["location"]


def test_the_limit_is_shared(admin_client, pending_req, locked):
    for _ in range(5):
        r = _post(admin_client, pending_req, "0000")
    blocked = i18n.t("lock.err.blocked", minutes=15)
    assert r.status_code == 403 and blocked in r.text
    assert blocked in unlock(admin_client, "notat").text
    r = _post(admin_client, pending_req, "1234")
    assert r.status_code == 403 and blocked in r.text
    assert _requests() == 1


def test_an_expired_request_costs_no_attempt(admin_client, locked):
    r = _post(admin_client, "no-such-request", "0000")
    assert r.status_code == 400 and i18n.t("oauth.expired") in r.text
    with main.db() as con:
        assert applock.get(con, ADMIN)["fails"] == 0


def test_existing_tokens_still_work(issued_token, locked):
    with make_client() as mcp:  # runs the lifespan, so the MCP session manager is up
        r = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                     headers={"Accept": "application/json, text/event-stream",
                              "Authorization": f"Bearer {issued_token}"})
    assert r.status_code == 200


def test_a_one_time_code_does_not_give_access_and_the_request_lives(admin_client, pending_req, locked):
    with main.db() as con:
        one_time = applock.reset(con, ADMIN)
    r = _post(admin_client, pending_req, one_time)
    assert r.status_code == 403 and i18n.t("lock.err.pick_new") in r.text and 'name="code"' in r.text
    assert _requests() == 1
    with main.db() as con:
        assert applock.get(con, ADMIN)["must_change"] == 1
    admin_client.post("/api/lock/code", json={"current": one_time, "code": "4321", "repeat": "4321"})
    r = _post(admin_client, pending_req, "4321")
    assert r.status_code == 303 and "code=" in r.headers["location"]
