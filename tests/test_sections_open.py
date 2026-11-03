"""Every front-page section (Favourites, each group, Other) is a list when open and a grid of icons when closed:
the stored open/closed state of Favourites and Other (app/home.py, prefs keys fav_open and rest_open), its route
and the markup."""
import re

import pytest

PAGE = "<!doctype html><html><head><title>A</title></head><body>a</body></html>"
U = "user@test.no"
X = "x@t.no"


def _prefs(hub, email=U):
    with hub.db() as con:
        return con.execute("SELECT key, value FROM prefs WHERE email=? ORDER BY key", (email,)).fetchall()


def _front(hub, *slugs):
    for s in slugs:
        hub.save_page(s, PAGE, create=True, private=False, title=s.upper())
    with hub.db() as con:
        for s in slugs:
            hub.home.set_added(con, U, s, True)


def _set(hub, **kw):
    with hub.db() as con:
        for k, v in kw.items():
            if k == "view":
                hub.home.set_view(con, U, v)
            else:
                hub.home._put(con, U, k, v)


def _sec(html, sid):
    start = html.find(f'<section id="{sid}"')
    return "" if start < 0 else html[start:html.find("</section>", start)]


def _front_html(client):
    html = client.get("/").text
    return html[:html.index("<dialog")]


# ---------------------------------------------------------------- storage
def test_missing_values_follow_the_stored_view(hub):
    with hub.db() as con:
        assert hub.home.get_section_open(con, X) == {"fav": False, "rest": False}  # never chose: icons
        hub.home.set_view(con, X, "cards")
        assert hub.home.get_section_open(con, X) == {"fav": True, "rest": True}
        hub.home.set_view(con, X, "icons")
        assert hub.home.get_section_open(con, X) == {"fav": False, "rest": False}


def test_reading_writes_nothing(hub):
    with hub.db() as con:
        hub.home.set_view(con, X, "cards")
        before = con.execute("SELECT key, value FROM prefs ORDER BY email, key").fetchall()
        hub.home.get_section_open(con, X)
        hub.home.get_section_open(con, "nobody@t.no")
        assert con.execute("SELECT key, value FROM prefs ORDER BY email, key").fetchall() == before


def test_each_section_keeps_its_own_value(hub):
    with hub.db() as con:
        hub.home.set_view(con, X, "cards")
        hub.home.set_section_open(con, X, "fav", False)
        assert hub.home.get_section_open(con, X) == {"fav": False, "rest": True}  # the other follows the view
        hub.home.set_view(con, X, "icons")
        hub.home.set_section_open(con, X, "rest", True)
        assert hub.home.get_section_open(con, X) == {"fav": False, "rest": True}


def test_set_get_round_trip_per_user(hub):
    with hub.db() as con:
        assert hub.home.set_section_open(con, X, "fav", True) is None
        hub.home.set_section_open(con, X, "rest", True)
        assert hub.home.get_section_open(con, X) == {"fav": True, "rest": True}
        hub.home.set_section_open(con, X, "fav", False)
        assert hub.home.get_section_open(con, X) == {"fav": False, "rest": True}
        assert hub.home.get_section_open(con, "y@t.no") == {"fav": False, "rest": False}
        assert hub.home._get(con, X, "fav_open", None) is False and hub.home._get(con, X, "rest_open", None) is True


def test_unknown_section_is_valueerror(hub):
    with hub.db() as con:
        for bad in ("g-1", "group", "", None, "Fav"):
            with pytest.raises(ValueError):
                hub.home.set_section_open(con, X, bad, True)
        assert con.execute("SELECT COUNT(*) FROM prefs").fetchone()[0] == 0


def test_a_stored_value_that_is_not_a_bool_is_ignored(hub):
    with hub.db() as con:
        hub.home.set_view(con, X, "cards")
        hub.home._put(con, X, "fav_open", "yes")
        hub.home._put(con, X, "rest_open", 0)
        assert hub.home.get_section_open(con, X) == {"fav": True, "rest": True}


# ---------------------------------------------------------------- route
def test_route_saves_and_answers_with_both(hub, user_client):
    r = user_client.post("/api/prefs/sections/open", json={"section": "fav", "open": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "open": {"fav": True, "rest": False}}
    r = user_client.post("/api/prefs/sections/open", json={"section": "rest", "open": True})
    assert r.json() == {"ok": True, "open": {"fav": True, "rest": True}}
    r = user_client.post("/api/prefs/sections/open", json={"section": "fav", "open": False})
    assert r.json() == {"ok": True, "open": {"fav": False, "rest": True}}
    with hub.db() as con:
        assert hub.home.get_section_open(con, U) == {"fav": False, "rest": True}
        assert hub.home.get_section_open(con, "admin@test.no") == {"fav": False, "rest": False}


def test_route_refuses_bad_bodies(hub, user_client, client):
    post = user_client.post
    assert post("/api/prefs/sections/open", json={"section": "g-1", "open": True}).status_code == 400
    assert post("/api/prefs/sections/open", json={"section": "group", "open": True}).status_code == 400
    assert post("/api/prefs/sections/open", json={"section": "fav"}).status_code == 400
    assert post("/api/prefs/sections/open", json={"open": True}).status_code == 400
    assert post("/api/prefs/sections/open", json={"section": "fav", "open": "yes"}).status_code == 400
    assert post("/api/prefs/sections/open", json={"section": 5, "open": True}).status_code == 400
    assert post("/api/prefs/sections/open", json=["fav"]).status_code == 400
    assert post("/api/prefs/sections/open", content="{", headers={"content-type": "application/json"}).status_code == 400
    assert not _prefs(hub)
    assert client.post("/api/prefs/sections/open", json={"section": "fav", "open": True}).status_code == 401


def test_route_is_one_write_transaction(hub, user_client, monkeypatch):
    seen = []
    real = hub.home.set_section_open

    def spy(con, *a):
        seen.append(con.in_transaction)  # BEGIN IMMEDIATE came first
        return real(con, *a)

    monkeypatch.setattr(hub.home, "set_section_open", spy)
    assert user_client.post("/api/prefs/sections/open", json={"section": "rest", "open": True}).status_code == 200
    assert seen == [True]


def test_old_view_route_still_works(hub, user_client):
    assert user_client.post("/api/prefs/view", json={"view": "cards"}).json() == {"ok": True, "view": "cards"}


# ---------------------------------------------------------------- the page: upgrade defaults (Review Focus 2)
def test_cards_user_sees_everything_open_as_before(hub, user_client):
    _front(hub, "a", "b", "c")
    _set(hub, view="cards", pins=["a"])
    with hub.db() as con:
        hub.home.create_group(con, U, "Jobb", "b")
    before = _prefs(hub)
    html = _front_html(user_client)
    for sid in ("fav", "rest"):
        sec = _sec(html, sid)
        assert 'data-open="1"' in sec and 'aria-expanded="true"' in sec and "gicons" not in sec and "<ul" in sec
    assert 'data-open="1"' in html and "gicons" not in html and " hidden>" not in html
    assert _prefs(hub) == before  # viewing stores nothing


def test_icons_user_sees_favourites_and_other_closed_groups_as_stored(hub, user_client):
    _front(hub, "a", "b", "c")
    _set(hub, view="icons", pins=["a"])
    with hub.db() as con:
        g = hub.home.create_group(con, U, "Jobb", "b")  # open when created
    before = _prefs(hub)
    html = _front_html(user_client)
    for sid in ("fav", "rest"):
        sec = _sec(html, sid)
        assert 'data-open="0"' in sec and 'aria-expanded="false"' in sec and 'class="gicons"' in sec
    assert 'data-open="1"' in _sec(html, f"g-{g['id']}")
    assert _prefs(hub) == before


def test_a_stored_choice_beats_the_view(hub, user_client):
    _front(hub, "a", "b")
    _set(hub, view="cards", pins=["a"], fav_open=False, rest_open=True)
    html = _front_html(user_client)
    assert 'data-open="0"' in _sec(html, "fav") and 'data-open="1"' in _sec(html, "rest")


# ---------------------------------------------------------------- the page: markup
def test_open_section_is_a_list_with_a_heading_button(hub, user_client):
    _front(hub, "a", "b", "c")
    _set(hub, pins=["a", "b"], fav_open=True, rest_open=True)
    html = _front_html(user_client)
    fav, rest = _sec(html, "fav"), _sec(html, "rest")
    assert fav.startswith('<section id="fav" class="box" data-order="pins" data-open="1">')
    assert ('<h3 class="sec"><button type="button" class="gtoggle" aria-expanded="true">'
            'Favoritter<span class="gcount">· 2</span>'
            '<span class="chev"></span></button></h3>') in fav
    assert '<ul class="cards">' in fav and fav.count('class="pin"') == 2 and "gicons" not in fav
    assert rest.startswith('<section id="rest"') and 'data-open="1"' in rest
    assert 'Alle apper<span class="gcount">· 1</span>' in rest and "gicons" not in rest
    assert '<ul class="cards">' in rest and rest.count('class="pin"') == 1


def test_closed_section_is_a_grid_of_links_without_pin_buttons(hub, user_client):
    _front(hub, "a", "b", "c")
    _set(hub, pins=["a", "b"], fav_open=False, rest_open=False)
    html = _front_html(user_client)
    for sid, slugs in (("fav", ["a", "b"]), ("rest", ["c"])):
        sec = _sec(html, sid)
        assert '<ul class="cards" hidden>' in sec and 'data-open="0"' in sec and 'aria-expanded="false"' in sec
        grid = sec[sec.index('<div class="gicons">'):]
        assert grid.count("<a ") == len(slugs) and "</div>" in grid
        assert "pin" not in grid and "<button" not in grid
        links = re.findall(r'<a class="gicon" href="([^"]+)" data-slug="([^"]+)">', grid)
        assert links == [(f"/a/{s}/", s) for s in slugs]
        for s in slugs:
            assert f"<span>{s.upper()}</span>" in grid
        assert grid.count('class="icon') == len(slugs)


def test_gicon_link_is_the_apps_open_url(hub, user_client):
    _front(hub, "a")
    html = _front_html(user_client)
    assert '<a class="gicon" href="/a/a/" data-slug="a">' in html


def test_link_card_icon_goes_through_go_and_opens_in_a_new_tab(hub, admin_client):
    admin_client.post("/api/link", data={"title": "Lenka", "url": "https://x.test/"})
    with hub.db() as con:
        slug = [a["slug"] for a in hub.list_artifacts("admin@test.no") if a["kind"] == "link"][0]
        hub.home._put(con, "admin@test.no", "apps", [slug])
    rest = _sec(_front_html(admin_client), "rest")
    grid = rest[rest.index("gicons"):]
    assert f'<a class="gicon" href="/go/{slug}" data-slug="{slug}" target="_blank" rel="noopener">' in grid


def test_closed_group_has_a_grid_of_links_too(hub, user_client):
    _front(hub, "a", "b", "c")
    with hub.db() as con:
        g = hub.home.create_group(con, U, "Jobb")
        hub.home.set_app_group(con, U, "a", g["id"])
        hub.home.set_app_group(con, U, "b", g["id"])
        hub.home.set_group_open(con, U, g["id"], False)
    sec = _sec(_front_html(user_client), f"g-{g['id']}")
    assert "gclosed" not in sec and '<ul class="cards" hidden>' in sec
    assert sec.count('<a class="gicon"') == 2 and "pin" not in sec[sec.index("gicons"):]


def test_name_and_title_are_escaped_in_the_grid(hub, user_client):
    hub.save_page("a", PAGE, create=True, private=False, title="<b>x</b>")
    with hub.db() as con:
        hub.home.set_added(con, U, "a", True)
    grid = _sec(_front_html(user_client), "rest")
    grid = grid[grid.index("gicons"):]
    assert "<span>&lt;b&gt;x&lt;/b&gt;</span>" in grid and "<b>x</b>" not in grid


def test_every_section_gets_summaries_for_a_view_icons_user(hub, user_client):
    _front(hub, "a", "b")
    _set(hub, view="icons", pins=["a"])
    with hub.db() as con:
        for s, text in (("a", "linje A"), ("b", "linje B")):
            con.execute(
                "INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES(?,?,?,?,?,?)",
                (s, U, "hub", "summary", '{"text": "%s"}' % text, 100),
            )
    html = _front_html(user_client)
    assert 'class="summary">linje A</p>' in _sec(html, "fav")
    assert 'class="summary">linje B</p>' in _sec(html, "rest")
    assert "linje" not in _sec(html, "rest")[_sec(html, "rest").index("gicons"):]  # the grid shows no lines


def test_recipes_run_for_a_view_icons_user(hub, user_client, monkeypatch):
    _front(hub, "a")
    called = []
    real = hub.card_lines
    monkeypatch.setattr(hub, "card_lines", lambda *a, **k: called.append(1) or real(*a, **k))
    assert user_client.get("/").status_code == 200
    assert called == [1]


def test_no_view_toggle_anywhere(hub, user_client):
    _front(hub, "a")
    for view in ("icons", "cards"):
        _set(hub, view=view)
        html = user_client.get("/").text
        assert "viewtog" not in html and "data-set-view" not in html and "/api/prefs/view" not in html
        assert "data-view=" not in html[:html.index("<dialog")]


def test_rest_heading_exists_when_it_is_the_only_section(hub, user_client):
    _front(hub, "a", "b")  # no favourites, no groups (Review Focus 5)
    html = _front_html(user_client)
    rest = _sec(html, "rest")
    assert "<h3 class=\"sec\"><button" in rest and "Alle apper" in rest and 'class="gtoggle"' in rest
    assert 'data-open="0"' in rest and 'class="gicons"' in rest
    _set(hub, rest_open=True)
    rest = _sec(_front_html(user_client), "rest")
    assert 'aria-expanded="true"' in rest and "gicons" not in rest and "Alle apper<span" in rest


def test_rest_is_called_other_when_there_are_groups(hub, user_client):
    _front(hub, "a", "b")
    with hub.db() as con:
        hub.home.create_group(con, U, "Jobb", "a")
    rest = _sec(_front_html(user_client), "rest")
    assert "Andre<span" in rest and "Alle apper" not in rest


def test_empty_rest_has_no_heading_and_favourites_none_at_all(hub, user_client):
    _front(hub, "a")
    _set(hub, pins=["a"])
    html = _front_html(user_client)
    assert _sec(html, "fav") and "<h3" not in _sec(html, "rest") and "gicons" not in _sec(html, "rest")
    assert _sec(html, "rest").startswith('<section id="rest" data-open=')  # no card for an empty Other
    _front(hub, "b")
    _set(hub, pins=[])
    assert _sec(_front_html(user_client), "fav") == ""


def test_every_section_with_apps_is_a_card(hub, user_client):
    _front(hub, "a", "b")
    _set(hub, pins=["a"])
    html = _front_html(user_client)
    assert _sec(html, "fav").startswith('<section id="fav" class="box"')
    assert _sec(html, "rest").startswith('<section id="rest" class="box"')
    css = _static("hub.css")
    box = _css_rule(css, ".box")
    assert "background: var(--card)" in box and "border-radius: 18px" in box and "box-shadow: var(--shadow)" in box
    assert css.count("--shadow:") == 3  # light, and dark both ways


def test_both_bottom_buttons(hub, user_client):
    _front(hub, "a")
    html = _front_html(user_client)
    assert '<button type="button" class="more" data-open-picker>＋ Ordne apper' in html
    assert '<button type="button" class="more" data-open-groups>Grupper</button>' in html
    assert html.index("data-open-picker") < html.index("data-open-groups")


def test_the_empty_page_keeps_its_one_big_button(hub, user_client):
    html = _front_html(user_client)
    assert 'class="addcard" data-open-picker' in html and "data-open-groups" not in html


# ---------------------------------------------------------------- home.js, drag.js, hub.css
def _static(name):
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "app" / "static" / name).read_text("utf-8")


def _css_rule(css, selector):
    m = re.search(rf"^\s*{re.escape(selector)} \{{(.*?)\}}", css, re.M | re.S)
    return m.group(1) if m else ""


def test_section_js_wiring():
    js, drag, css = _static("home.js"), _static("drag.js"), _static("hub.css")
    # Favourites and Other fold through their own route; a section folded here builds the same grid as the server
    assert "/api/prefs/sections/open" in js and "/api/prefs/groups/open" in js
    assert '"gicons"' in js and '"gicon"' in js and ".gicons" in js
    # v1.6 leftovers are gone: the folded icon row and the view toggle
    for gone in ("gclosed", "data-set-view", "pressView", "/api/prefs/view", "icon-xs", ".view"):
        assert gone not in js, gone
    # Only the groups may fold: the guard that kept Favourites and Other from folding is gone
    assert 'closest("section.group"); // Favourites' not in js
    # The icons in a closed section: hold opens the menu, hold and move reorders
    assert ".gicon" in drag and ".gicons" in drag and "hub:menu" in drag
    assert ".grid" not in drag
    grid = _css_rule(css, ".gicons")
    assert "display: grid" in grid
    assert re.search(r"@media \(max-width: 480px\) \{[^}]*\.gicons \{[^}]*repeat\(4, minmax\(0, 1fr\)\)", css)
    assert "--size: 50px" in _css_rule(css, ".gicon .icon")
    name = _css_rule(css, ".gicon > span:not(.icon)")
    assert "white-space: nowrap" in name and "text-overflow: ellipsis" in name
    assert "min-height: 44px" in _css_rule(css, ".gicon")
    for gone in (".gclosed", ".viewtog", ".grid "):
        assert gone not in css, gone
    assert ".gicon.lifted" in css and ".gicon.sliding" in css


def test_offline_layout_shows_every_section_as_lists():
    js = _static("home.js")
    start = js.index("async function enterOffline")
    body = js[start:js.index("if (offline()) enterOffline()", start)]
    assert "#fav, section.group, #rest" in body and 'ul.className = "cards"' in body
    assert 'sec.className = "box"' in body
    assert "dataset.view" not in body and '"grid"' not in body
