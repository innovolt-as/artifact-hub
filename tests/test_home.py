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


PAGE = "<!doctype html><html><head><title>A</title></head><body>a</body></html>"


def test_prefs_api_view(hub, user_client, admin_client):
    r = user_client.post("/api/prefs/view", json={"view": "cards"})
    assert r.status_code == 200 and r.json() == {"ok": True, "view": "cards"}
    with hub.db() as con:
        assert hub.home.get_prefs(con, "user@test.no")["view"] == "cards"
        assert hub.home.get_prefs(con, "admin@test.no")["view"] == "icons"


def test_prefs_api_pin(hub, user_client):
    hub.save_page("a", PAGE, create=True, private=False)
    r = user_client.post("/api/prefs/pin", json={"slug": "a", "pinned": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "pins": ["a"]}
    r = user_client.post("/api/prefs/pin", json={"slug": "a", "pinned": False})
    assert r.json() == {"ok": True, "pins": []}


def test_prefs_api_rejects(hub, user_client, client):
    hub.save_page("a", PAGE, create=True, private=False)
    hub.save_page("hemmelig", PAGE, create=True, private=True)
    assert user_client.post("/api/prefs/view", json={"view": "x"}).status_code == 400
    assert user_client.post("/api/prefs/pin", json={"slug": "finnes-ikke", "pinned": True}).status_code == 404
    assert user_client.post("/api/prefs/pin", json={"slug": "hemmelig", "pinned": True}).status_code == 404
    assert user_client.post("/api/prefs/pin", json={"slug": "a", "pinned": "ja"}).status_code == 400
    assert client.post("/api/prefs/view", json={"view": "cards"}).status_code == 401


def _visits(hub, email):
    with hub.db() as con:
        return [r["slug"] for r in con.execute("SELECT slug FROM visits WHERE email=?", (email,))]


def test_visit_logged_on_open_not_assets(hub, user_client):
    d = hub.ARTIFACTS_DIR / "m"
    d.mkdir()
    (d / "index.html").write_text(PAGE, "utf-8")
    (d / "sw.js").write_text("// sw", "utf-8")
    assert user_client.get("/a/m/").status_code == 200
    assert user_client.get("/a/m/sw.js").status_code == 200
    assert _visits(hub, "user@test.no") == ["m"]


def test_go_redirects_and_logs(hub, user_client):
    (hub.ARTIFACTS_DIR / "kort.link.json").write_text(json.dumps({"title": "Kort", "url": "https://x.no/y"}))
    r = user_client.get("/go/kort")
    assert r.status_code == 302 and r.headers["location"] == "https://x.no/y"
    assert _visits(hub, "user@test.no") == ["kort"]
    link = next(a for a in hub.list_artifacts("user@test.no") if a["slug"] == "kort")
    assert link["open_url"] == "/go/kort" and link["url"] == "https://x.no/y"


def test_go_404(hub, user_client):
    hub.save_page("side", PAGE, create=True, private=False)
    (hub.ARTIFACTS_DIR / "skjult.link.json").write_text(
        json.dumps({"title": "S", "url": "https://x.no/", "admin_only": True}))
    for slug in ("finnes-ikke", "side", "skjult"):
        assert user_client.get(f"/go/{slug}").status_code == 404
    assert _visits(hub, "user@test.no") == []


def _section(html, sid):
    start = html.find(f'<section id="{sid}"')
    return "" if start < 0 else html[start:html.find("</section>", start)]


def _two_public_pages(hub):
    hub.save_page("a", PAGE, create=True, private=False, title="Alfa")
    hub.save_page("b", PAGE, create=True, private=False, title="Beta")


def test_index_sections(hub, user_client):
    _two_public_pages(hub)
    html = user_client.get("/").text
    assert 'id="top"' not in html and 'data-slug="a"' in _section(html, "rest")
    _visit(hub, "user@test.no", "a")
    html = user_client.get("/").text
    assert 'data-slug="a"' in _section(html, "top") and 'data-slug="a"' not in _section(html, "rest")
    assert 'data-slug="b"' in _section(html, "rest")


def test_index_cards_shows_escaped_summary(hub, user_client):
    _two_public_pages(hub)
    with hub.db() as con:
        hub.home.set_view(con, "user@test.no", "cards")
        _doc_summary(con, "a", "user@test.no", {"text": "<b>x</b> 93 ▼1"}, 100)
    html = user_client.get("/").text
    assert 'data-view="cards"' in html
    assert "&lt;b&gt;x&lt;/b&gt; 93 ▼1" in html and "<b>x</b>" not in html
    assert 'class="pin"' in html


def test_index_icons_hides_summary(hub, user_client):
    _two_public_pages(hub)
    with hub.db() as con:
        _doc_summary(con, "a", "user@test.no", {"text": "hemmelig linje"}, 100)
    html = user_client.get("/").text
    assert 'data-view="icons"' in html and "hemmelig linje" not in html


def test_index_new_dot(hub, user_client):
    _two_public_pages(hub)
    _visit(hub, "user@test.no", "a", at=1)
    html = user_client.get("/").text
    item = html[html.find('data-slug="a"'):]
    assert 'class="dot"' in item[: item.find("</li>")]
    assert html.count('class="dot"') == 1


def test_admin_page_header_unchanged(admin_client):
    html = admin_client.get("/admin").text
    assert 'class="top"' in html and 'class="hero"' not in html


def test_new_dot_ignores_same_second(hub):
    _visit(hub, "x@t.no", "a", at=200)
    top, _ = _sections(hub, "x@t.no", [{"slug": "a", "title": "a", "updated": 200.7}], now=300)
    assert top[0]["new"] is False


def test_manifest_served(hub, client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(r.text)
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["name"] == hub.SITE_NAME


def test_base_links_manifest(user_client):
    html = user_client.get("/").text
    assert 'rel="manifest"' in html and 'name="theme-color"' in html
