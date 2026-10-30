"""The Claude connection reaches locked apps on purpose: the lock is in the routes, not in doc_scope."""
import json

from app import connector
from tests.conftest import lock
from tests.test_connector import PAGE, call, mcp, text, token  # noqa: F401  (fixtures)


def _locked_app(hub, slug="mat", seed=None):
    """An app that admin@test.no has locked, with `seed` stored under days/a before it was locked."""
    (hub.ARTIFACTS_DIR / f"{slug}.html").write_text(PAGE)
    (hub.ARTIFACTS_DIR / f"{slug}.meta.json").write_text("{}")
    if seed:
        hub.doc_set(slug, "admin@test.no", "days/a", seed)
    lock("admin@test.no", slug)


def test_claude_reads_a_locked_app(mcp, token, hub):  # noqa: F811
    _locked_app(hub, seed={"n": 1})
    got = json.loads(text(call(mcp, token, "get_app_data", slug="mat", path="days/a")))
    assert got["exists"] is True and got["data"] == {"n": 1}


def test_claude_writes_a_locked_app(mcp, token, hub):  # noqa: F811
    _locked_app(hub)
    res = call(mcp, token, "set_app_data", slug="mat", path="days/a", data={"n": 2})
    assert not res.get("isError"), res
    assert hub.doc_get("mat", "admin@test.no", "days/a") == {"n": 2}


def test_claude_lists_data_in_a_locked_app(mcp, token, hub):  # noqa: F811
    _locked_app(hub, seed={"n": 1})
    assert json.loads(text(call(mcp, token, "list_app_data", slug="mat"))) == {"days": ["a"]}
    assert json.loads(text(call(mcp, token, "list_app_data", slug="mat", collection="days"))) == {"a": {"n": 1}}


def test_get_app_shows_the_card_of_a_locked_app(mcp, token, hub):  # noqa: F811
    page = ("<!doctype html><html><head><title>T</title></head><body>"
            "<script data-hub-card>function hubCard() { return 'tre'; }</script></body></html>")
    call(mcp, token, "create_app", slug="mat", html=page, title="Mat")
    lock("admin@test.no", "mat")
    assert json.loads(text(call(mcp, token, "get_app", slug="mat")))["card"] == {"text": "tre"}


def test_update_app_works_on_a_locked_app(mcp, token, hub):  # noqa: F811
    call(mcp, token, "create_app", slug="mat", html=PAGE, title="Mat")
    lock("admin@test.no", "mat")
    res = call(mcp, token, "update_app", slug="mat", html=PAGE.replace("Hei", "Hallo"))
    assert not res.get("isError"), res


def test_the_instructions_mention_the_lock():
    assert "localStorage" in connector.INSTRUCTIONS
