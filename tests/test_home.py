"""Front page: per-user visits, pins, view mode, app summaries and the new-dot (app/home.py)."""
import json

import pytest

DAY = 86400
NOW = 1_800_000_000


def _apps(*slugs, updated=0):
    return [{"slug": s, "title": s, "updated": updated} for s in slugs]


def _visit(hub, email, slug, times=1, at=NOW):
    with hub.db() as con:
        for _ in range(times):
            hub.home.record_visit(con, email, slug, now=at)


def _sections(hub, email, apps, now=NOW):
    with hub.db() as con:
        stats = hub.home.visit_stats(con, email, now=now)
        pins = hub.home.get_prefs(con, email)["pins"]
    return hub.home.build_sections(apps, stats, pins)


def _slugs(items):
    return [a["slug"] for a in items]


def test_most_used_order_and_limit(hub):
    for slug, n in {"a": 3, "b": 5, "c": 1, "d": 2, "e": 4}.items():
        _visit(hub, "x@t.no", slug, n)
    top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e"))
    assert _slugs(top) == ["b", "e", "a", "d"]
    assert _slugs(rest) == ["c"]


def test_pins_first_then_usage(hub):
    for slug, n in {"a": 3, "b": 5, "c": 1, "d": 2, "e": 4}.items():
        _visit(hub, "x@t.no", slug, n)
    with hub.db() as con:
        hub.home.set_pin(con, "x@t.no", "c", True)
    top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e"))
    assert _slugs(top) == ["c", "b", "e", "a"]
    assert top[0]["pinned"] is True and top[1]["pinned"] is False
    assert _slugs(rest) == ["d"]


def test_many_pins_all_shown(hub):
    with hub.db() as con:
        for s in ["e", "d", "c", "b", "a"]:
            hub.home.set_pin(con, "x@t.no", s, True)
    top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e", "f"))
    assert _slugs(top) == ["e", "d", "c", "b", "a"]
    assert _slugs(rest) == ["f"]


def test_old_visits_ignored_and_purged(hub):
    _visit(hub, "x@t.no", "a", at=NOW - 31 * DAY)
    _visit(hub, "x@t.no", "b", at=NOW - 91 * DAY)
    with hub.db() as con:
        assert hub.home.visit_stats(con, "x@t.no", now=NOW)["a"]["count"] == 0
        hub.home.record_visit(con, "x@t.no", "c", now=NOW)
        rows = con.execute("SELECT slug FROM visits WHERE email=?", ("x@t.no",)).fetchall()
    assert sorted(r["slug"] for r in rows) == ["a", "c"]
    top, _ = _sections(hub, "x@t.no", _apps("a", "b"))
    assert top == []


def test_no_visits_no_pins_hides_section(hub):
    top, rest = _sections(hub, "x@t.no", _apps("a", "b"))
    assert top == [] and _slugs(rest) == ["a", "b"]


def test_users_isolated(hub):
    _visit(hub, "x@t.no", "a", 3)
    with hub.db() as con:
        hub.home.set_pin(con, "x@t.no", "b", True)
        hub.home.set_view(con, "x@t.no", "cards")
        assert hub.home.get_prefs(con, "y@t.no") == {"view": "icons", "pins": []}
    top, _ = _sections(hub, "y@t.no", _apps("a", "b"))
    assert top == []


def test_unknown_or_hidden_pin_skipped(hub):
    with hub.db() as con:
        hub.home.set_pin(con, "x@t.no", "finnes-ikke", True)
    top, rest = _sections(hub, "x@t.no", _apps("a"))
    assert top == [] and _slugs(rest) == ["a"]


def test_new_dot(hub):
    apps = _apps("a", "b", "c", updated=200)
    _visit(hub, "x@t.no", "a", at=100)
    _visit(hub, "x@t.no", "b", at=300)
    top, rest = _sections(hub, "x@t.no", apps, now=400)
    flags = {a["slug"]: a["new"] for a in top + rest}
    assert flags == {"a": True, "b": False, "c": False}


def test_prefs_defaults_and_validation(hub):
    with hub.db() as con:
        assert hub.home.get_prefs(con, "x@t.no") == {"view": "icons", "pins": []}
        with pytest.raises(ValueError):
            hub.home.set_view(con, "x@t.no", "list")
        hub.home.set_view(con, "x@t.no", "cards")
        assert hub.home.set_pin(con, "x@t.no", "a", True) == ["a"]
        assert hub.home.set_pin(con, "x@t.no", "a", True) == ["a"]
        assert hub.home.set_pin(con, "x@t.no", "b", True) == ["a", "b"]
        assert hub.home.set_pin(con, "x@t.no", "a", False) == ["b"]
        assert hub.home.get_prefs(con, "x@t.no") == {"view": "cards", "pins": ["b"]}


def _doc_summary(con, slug, owner, data, at):
    con.execute(
        "INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES(?,?,?,?,?,?)",
        (slug, owner, "hub", "summary", json.dumps(data), at),
    )


def _data_summary(con, app, email, data, at):
    con.execute(
        "INSERT INTO app_data(email, app, key, value, updated) VALUES(?,?,?,?,?)",
        (email, app, "hub/summary", json.dumps(data), at),
    )


def test_summaries_both_sources_newest_wins_and_cut(hub):
    with hub.db() as con:
        _doc_summary(con, "a", "x@t.no", {"text": "A"}, 100)
        _data_summary(con, "a", "x@t.no", {"text": "B"}, 200)
        _doc_summary(con, "b", "x@t.no", {"text": "x" * 200}, 100)
        _doc_summary(con, "c", "x@t.no", {"text": 5}, 100)
        _doc_summary(con, "d", "x@t.no", {}, 100)
        _data_summary(con, "e", "x@t.no", {"text": ""}, 100)
        _doc_summary(con, "f", "y@t.no", {"text": "andres"}, 100)
        got = hub.home.summaries(con, "x@t.no", ["a", "b", "c", "d", "e", "f"])
    assert got["a"] == "B"
    assert len(got["b"]) == 140
    assert set(got) == {"a", "b"}
