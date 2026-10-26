"""Front page: per-user visits, pins, view mode, app summaries and the new-dot (app/home.py)."""
import json
import re

import pytest

DAY = 86400
NOW = 1_800_000_000


def _apps(*slugs, updated=0):
    return [{"slug": s, "title": s, "updated": updated} for s in slugs]


def _visit(hub, email, slug, times=1, at=NOW):
    """`times` separate opens, 11 minutes apart and ending at `at` (reloads within 10 minutes count once)."""
    with hub.db() as con:
        for i in reversed(range(times)):
            hub.home.record_visit(con, email, slug, now=at - i * 660)


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
    favs, top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e"))
    assert favs == [] and _slugs(top) == ["b", "e", "a", "d"]
    assert _slugs(rest) == ["c"]


def test_favorites_do_not_take_most_used_slots(hub):
    for slug, n in {"a": 3, "b": 5, "c": 1, "d": 2, "e": 4, "f": 6}.items():
        _visit(hub, "x@t.no", slug, n)
    with hub.db() as con:
        for s in ["c", "f", "a"]:
            hub.home.set_pin(con, "x@t.no", s, True)
    favs, top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e", "f", "g"))
    assert _slugs(favs) == ["c", "f", "a"] and all(a["pinned"] for a in favs)
    assert _slugs(top) == ["b", "e", "d"] and not any(a["pinned"] for a in top)
    assert _slugs(rest) == ["g"]


def test_many_pins_all_shown(hub):
    with hub.db() as con:
        for s in ["e", "d", "c", "b", "a"]:
            hub.home.set_pin(con, "x@t.no", s, True)
    favs, top, rest = _sections(hub, "x@t.no", _apps("a", "b", "c", "d", "e", "f"))
    assert _slugs(favs) == ["e", "d", "c", "b", "a"]
    assert top == [] and _slugs(rest) == ["f"]


def test_old_visits_ignored_and_purged(hub):
    _visit(hub, "x@t.no", "a", at=NOW - 31 * DAY)
    _visit(hub, "x@t.no", "b", at=NOW - 91 * DAY)
    with hub.db() as con:
        assert hub.home.visit_stats(con, "x@t.no", now=NOW)["a"]["count"] == 0
        hub.home.record_visit(con, "x@t.no", "c", now=NOW)
        rows = con.execute("SELECT slug FROM visits WHERE email=?", ("x@t.no",)).fetchall()
    assert sorted(r["slug"] for r in rows) == ["a", "c"]
    _, top, _ = _sections(hub, "x@t.no", _apps("a", "b"))
    assert top == []


def test_no_visits_no_pins_hides_section(hub):
    favs, top, rest = _sections(hub, "x@t.no", _apps("a", "b"))
    assert favs == [] and top == [] and _slugs(rest) == ["a", "b"]


def test_users_isolated(hub):
    _visit(hub, "x@t.no", "a", 3)
    with hub.db() as con:
        hub.home.set_pin(con, "x@t.no", "b", True)
        hub.home.set_view(con, "x@t.no", "cards")
        assert hub.home.get_prefs(con, "y@t.no") == {"view": "icons", "pins": [], "apps": [], "seen": None}
    favs, top, _ = _sections(hub, "y@t.no", _apps("a", "b"))
    assert favs == [] and top == []


def test_unknown_or_hidden_pin_skipped(hub):
    with hub.db() as con:
        hub.home.set_pin(con, "x@t.no", "finnes-ikke", True)
    favs, top, rest = _sections(hub, "x@t.no", _apps("a"))
    assert favs == [] and top == [] and _slugs(rest) == ["a"]


def test_new_dot(hub):
    apps = _apps("a", "b", "c", updated=200)
    _visit(hub, "x@t.no", "a", at=100)
    _visit(hub, "x@t.no", "b", at=300)
    favs, top, rest = _sections(hub, "x@t.no", apps, now=400)
    flags = {a["slug"]: a["new"] for a in favs + top + rest}
    assert flags == {"a": True, "b": False, "c": False}


def test_prefs_defaults_and_validation(hub):
    with hub.db() as con:
        assert hub.home.get_prefs(con, "x@t.no") == {"view": "icons", "pins": [], "apps": [], "seen": None}
        with pytest.raises(ValueError):
            hub.home.set_view(con, "x@t.no", "list")
        hub.home.set_view(con, "x@t.no", "cards")
        assert hub.home.set_pin(con, "x@t.no", "a", True) == ["a"]
        assert hub.home.set_pin(con, "x@t.no", "a", True) == ["a"]
        assert hub.home.set_pin(con, "x@t.no", "b", True) == ["a", "b"]
        assert hub.home.set_pin(con, "x@t.no", "a", False) == ["b"]
        assert hub.home.get_prefs(con, "x@t.no") == {"view": "cards", "pins": ["b"], "apps": [], "seen": None}


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
    """Two shared apps, both on user@test.no's front page."""
    hub.save_page("a", PAGE, create=True, private=False, title="Alfa")
    hub.save_page("b", PAGE, create=True, private=False, title="Beta")
    with hub.db() as con:
        for s in ("a", "b"):
            hub.home.set_added(con, "user@test.no", s, True)


def test_index_sections(hub, user_client):
    _two_public_pages(hub)
    html = user_client.get("/").text
    assert 'id="top"' not in html and 'data-slug="a"' in _section(html, "rest")
    _visit(hub, "user@test.no", "a")
    html = user_client.get("/").text
    assert 'data-slug="a"' in _section(html, "top") and 'data-slug="a"' not in _section(html, "rest")
    assert 'data-slug="b"' in _section(html, "rest") and 'id="fav"' not in html


def test_index_favorites_section(hub, user_client):
    _two_public_pages(hub)
    _visit(hub, "user@test.no", "a")
    with hub.db() as con:
        hub.home.set_pin(con, "user@test.no", "b", True)
    html = user_client.get("/").text
    fav = _section(html, "fav")
    assert "Favoritter" in fav and 'data-slug="b"' in fav and 'data-slug="a"' not in fav
    assert 'data-slug="a"' in _section(html, "top") and 'data-slug="b"' not in _section(html, "top")
    assert html.index('id="fav"') < html.index('id="top"') < html.index('id="rest"')


def test_favorite_labels(hub, user_client):
    _two_public_pages(hub)
    with hub.db() as con:
        hub.home.set_view(con, "user@test.no", "cards")
        hub.home.set_pin(con, "user@test.no", "b", True)
    html = user_client.get("/").text
    assert 'aria-label="Fjern fra favoritter: Beta"' in html and 'aria-label="Legg til i favoritter: Alfa"' in html
    js = user_client.get("/static/home.js").text + html  # the texts now reach home.js as JSON in the page
    assert "Legg til i favoritter" in js and "Fjern fra favoritter" in js and "Fest øverst" not in js


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
    _, top, _ = _sections(hub, "x@t.no", [{"slug": "a", "title": "a", "updated": 200.7}], now=300)
    assert top[0]["new"] is False


def test_manifest_served(hub, client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(r.text)
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["name"] == hub.SITE_NAME


def test_base_links_manifest(user_client):
    html = user_client.get("/").text
    assert 'rel="manifest"' in html and 'name="theme-color"' in html


def test_reload_within_ten_minutes_is_one_visit(hub):
    _visit(hub, "x@t.no", "a", at=NOW)
    _visit(hub, "x@t.no", "a", at=NOW + 300)
    _visit(hub, "x@t.no", "b", at=NOW + 300)
    _visit(hub, "x@t.no", "a", at=NOW + 900)
    with hub.db() as con:
        stats = hub.home.visit_stats(con, "x@t.no", now=NOW + 900)
    assert stats["a"] == {"count": 2, "last": NOW + 900} and stats["b"]["count"] == 1


def test_no_translucent_status_bar(user_client):
    assert "black-translucent" not in user_client.get("/").text


# ---------------------------------------------------------------- choosing apps for the front page
def _prefs(hub, email):
    with hub.db() as con:
        return hub.home.get_prefs(con, email)


def test_admin_starts_with_everything_once(hub):
    with hub.db() as con:
        hub.home.start(con, "admin@test.no", ["a", "b"], admin=True)
        hub.home.start(con, "admin@test.no", ["a", "b", "c"], admin=True)
        hub.home.start(con, "x@t.no", ["a"], admin=False)
    assert _prefs(hub, "admin@test.no")["apps"] == ["a", "b"] and _prefs(hub, "admin@test.no")["seen"] == ["a", "b"]
    assert _prefs(hub, "x@t.no")["apps"] == [] and _prefs(hub, "x@t.no")["seen"] is None


def test_set_added_marks_seen(hub):
    with hub.db() as con:
        assert hub.home.set_added(con, "x@t.no", "a", True) == ["a"]
        assert hub.home.set_added(con, "x@t.no", "b", True) == ["a", "b"]
        assert hub.home.set_added(con, "x@t.no", "a", False) == ["b"]
    assert sorted(_prefs(hub, "x@t.no")["seen"]) == ["a", "b"]


def test_picker_puts_unseen_first(hub):
    out = hub.home.picker(_apps("a", "b", "c", "d"), ["b"], ["a", "b"])
    assert _slugs(out) == ["c", "d", "a", "b"]
    assert [a["unseen"] for a in out] == [True, True, False, False]
    assert [a["added"] for a in out] == [False, False, False, True]
    assert not any(a["unseen"] for a in hub.home.picker(_apps("a", "b"), [], None))
    assert not hub.home.picker(_apps("a"), ["a"], [])[0]["unseen"]


def test_add_for_only_users_with_choices(hub):
    with hub.db() as con:
        hub.home.start(con, "admin@test.no", ["a"], admin=True)
        hub.home.add_for(con, ["admin@test.no", "annen@admin.no"], "z")
    assert _prefs(hub, "admin@test.no")["apps"] == ["a", "z"] and "z" in _prefs(hub, "admin@test.no")["seen"]
    assert _prefs(hub, "annen@admin.no")["apps"] == [] and _prefs(hub, "annen@admin.no")["seen"] is None


def test_rename_follows_choices_pins_and_seen(hub):
    with hub.db() as con:
        hub.home.set_added(con, "x@t.no", "a", True)
        hub.home.set_pin(con, "x@t.no", "a", True)
        hub.home.rename(con, "a", "a2")
    p = _prefs(hub, "x@t.no")
    assert p["apps"] == ["a2"] and p["pins"] == ["a2"] and p["seen"] == ["a2"]


def test_index_shows_only_chosen(hub, make_page, user_client):
    make_page("a", title="Alfa")
    make_page("b", title="Beta")
    assert 'data-slug="a"' not in _section(user_client.get("/").text, "rest")
    r = user_client.post("/api/prefs/apps", json={"slug": "a", "added": True})
    assert r.status_code == 200 and r.json()["apps"] == ["a"]
    rest = _section(user_client.get("/").text, "rest")
    assert 'data-slug="a"' in rest and 'data-slug="b"' not in rest


def test_prefs_apps_api_rejects(hub, make_page, user_client, client):
    make_page("a")
    make_page("p", "people", ["venn@test.no"])
    assert user_client.post("/api/prefs/apps", json={"slug": "p", "added": True}).status_code == 404
    assert user_client.post("/api/prefs/apps", json={"slug": "a", "added": "ja"}).status_code == 400
    assert user_client.post("/api/prefs/apps", data={"slug": "a"}).status_code == 415
    assert client.post("/api/prefs/apps", json={"slug": "a", "added": True}).status_code == 401


def test_prefs_seen_api(hub, make_page, user_client):
    make_page("a")
    make_page("p", "people", ["venn@test.no"])
    assert user_client.post("/api/prefs/seen", json={}).status_code == 200
    assert _prefs(hub, "user@test.no")["seen"] == ["a"]


def test_lost_access_hides_then_returns(hub, make_page, admin_client, friend_client):
    make_page("p", "people", ["venn@test.no"])
    friend_client.post("/api/prefs/apps", json={"slug": "p", "added": True})
    friend_client.post("/api/prefs/pin", json={"slug": "p", "pinned": True})
    admin_client.post("/api/access", json={"slug": "p", "level": "admin", "people": ["venn@test.no"]})
    assert 'data-slug="p"' not in friend_client.get("/").text
    assert friend_client.post("/api/prefs/apps", json={"slug": "p", "added": False}).status_code == 404
    admin_client.post("/api/access", json={"slug": "p", "level": "people", "people": ["venn@test.no"]})
    assert 'data-slug="p"' in _section(friend_client.get("/").text, "fav")


def test_admin_front_page_keeps_everything(hub, make_page, admin_client):
    make_page("a")
    make_page("q", "admin")
    rest = _section(admin_client.get("/").text, "rest")
    assert 'data-slug="a"' in rest and 'data-slug="q"' in rest


def test_new_apps_land_on_admin_front_page_only(hub, admin_client, user_client, upload):
    admin_client.get("/")
    upload(admin_client, "c.html", "<body>c</body>")
    hub.save_page("d", PAGE, create=True, private=False)
    admin_client.post("/api/link", data={"title": "Lenke", "url": "https://x.no/"})
    rest = _section(admin_client.get("/").text, "rest")
    assert all(f'data-slug="{s}"' in rest for s in ("c", "d", "lenke"))
    assert 'data-slug="c"' not in _section(user_client.get("/").text, "rest")
    with hub.db() as con:
        hub.home.set_added(con, "admin@test.no", "c", False)
    upload(admin_client, "c.html", "<body>c2</body>")  # replacing is not new
    assert 'data-slug="c"' not in _section(admin_client.get("/").text, "rest")


def test_new_address_keeps_app_on_front_page(hub, make_page, admin_client, user_client):
    make_page("a")
    user_client.post("/api/prefs/apps", json={"slug": "a", "added": True})
    assert admin_client.post("/api/edit", data={"slug": "a", "new_slug": "a2"}).status_code == 200
    assert 'data-slug="a2"' in _section(user_client.get("/").text, "rest")


# ---------------------------------------------------------------- the "Velg apper" list on the front page
def _picker(html):
    return html[html.find('id="picker"'):html.find("</dialog>")]


def test_empty_front_page_shows_add_card(hub, make_page, user_client):
    make_page("a", title="Alfa")
    html = user_client.get("/").text
    assert 'class="addcard"' in html and "Legg til apper" in html and "Velg hvilke apper du vil ha på forsiden din" in html
    assert "Ingen apper ennå" not in html and 'class="more"' not in html
    p = _picker(html)
    assert "Velg apper" in p and 'data-slug="a"' in p and "Alfa" in p and "checked" not in p


def test_after_choosing_small_button_and_checked(hub, make_page, user_client):
    make_page("a", title="Alfa")
    make_page("b", title="Beta")
    user_client.post("/api/prefs/apps", json={"slug": "a", "added": True})
    html = user_client.get("/").text
    assert 'class="more"' in html and "Legg til eller fjern apper" in html and 'class="addcard"' not in html
    assert re.search(r'data-slug="a"[^>]*checked', _picker(html)) and not re.search(r'data-slug="b"[^>]*checked', _picker(html))


def test_new_apps_first_with_dot_until_seen(hub, make_page, user_client):
    make_page("a", title="Alfa")
    user_client.post("/api/prefs/apps", json={"slug": "a", "added": True})
    make_page("b", title="Beta")
    html = user_client.get("/").text
    p = _picker(html)
    assert p.index('data-slug="b"') < p.index('data-slug="a"') and p.count(">Ny<") == 1
    more = html[html.find('class="more"'):]
    assert 'class="dot"' in more[:more.find("</button>")]
    user_client.post("/api/prefs/seen", json={})
    html = user_client.get("/").text
    assert ">Ny<" not in _picker(html) and 'class="dot"' not in html[html.find('class="more"'):].split("</button>")[0]


def test_picker_empty_text_and_escaping(hub, make_page, user_client):
    assert "Det finnes ingen apper ennå." in _picker(user_client.get("/").text)
    make_page("x", title="<b>x</b>")
    p = _picker(user_client.get("/").text)
    assert "&lt;b&gt;x&lt;/b&gt;" in p and "<b>x</b>" not in p


def test_admin_picker_shows_lock(hub, make_page, admin_client):
    make_page("q", "admin", title="Hemmelig")
    p = _picker(admin_client.get("/").text)
    assert "Hemmelig" in p and "🔒" in p
