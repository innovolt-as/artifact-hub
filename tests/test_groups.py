"""Each user's own groups for the front page (app/home.py, prefs key "groups")."""
import json
from pathlib import Path

import pytest

from tests.conftest import make_client

PAGE = "<!doctype html><html><head><title>A</title></head><body>a</body></html>"
X = "x@t.no"


def _mk(hub, *names):
    """Create groups called `names`; returns their ids."""
    with hub.db() as con:
        return [hub.home.create_group(con, X, n)["id"] for n in names]


def _groups(hub, email=X):
    with hub.db() as con:
        return hub.home.get_groups(con, email)


def _view(hub, email=X):
    """Group id -> slugs."""
    return {g["id"]: g["slugs"] for g in _groups(hub, email)}


def _store(hub, email, value):
    with hub.db() as con:
        hub.home._put(con, email, "groups", value)


# ---------------------------------------------------------------- storage
def test_create_rename_delete(hub):
    with hub.db() as con:
        g = hub.home.create_group(con, X, "Jobb")
        assert set(g) == {"id", "name", "slugs", "open"}
        assert g["name"] == "Jobb" and g["slugs"] == [] and g["open"] is True and len(g["id"]) == 8
        h = hub.home.create_group(con, X, "Fritid")
        assert [x["name"] for x in hub.home.get_groups(con, X)] == ["Jobb", "Fritid"]
        assert hub.home.rename_group(con, X, g["id"], "Arbeid")["name"] == "Arbeid"
        assert [x["name"] for x in hub.home.get_groups(con, X)] == ["Arbeid", "Fritid"]
        assert hub.home.delete_group(con, X, g["id"]) is None
        assert [x["id"] for x in hub.home.get_groups(con, X)] == [h["id"]]
        assert hub.home.get_groups(con, "y@t.no") == []  # nobody else's


def test_name_is_trimmed_and_validated(hub):
    with hub.db() as con:
        assert hub.home.create_group(con, X, "  Jobb \n")["name"] == "Jobb"
        assert hub.home.create_group(con, X, "x" * 40)["name"] == "x" * 40
        for bad in ("", "   ", "x" * 41, None, 5):
            with pytest.raises(ValueError, match="1–40"):
                hub.home.create_group(con, X, bad)
        gid = hub.home.get_groups(con, X)[0]["id"]
        with pytest.raises(ValueError, match="1–40"):
            hub.home.rename_group(con, X, gid, " ")
        assert len(hub.home.get_groups(con, X)) == 2


def test_names_are_unique_ignoring_case(hub):
    with hub.db() as con:
        g = hub.home.create_group(con, X, "Jobb")
        with pytest.raises(ValueError, match="«jobb»"):
            hub.home.create_group(con, X, "jobb")
        other = hub.home.create_group(con, X, "Fritid")
        with pytest.raises(ValueError, match="«JOBB»"):
            hub.home.rename_group(con, X, other["id"], " JOBB ")
        assert hub.home.rename_group(con, X, g["id"], "JOBB")["name"] == "JOBB"  # its own name, another case
        assert hub.home.create_group(con, "y@t.no", "Jobb")["name"] == "Jobb"  # per user


def test_at_most_thirty_groups(hub):
    with hub.db() as con:
        for i in range(hub.home.GROUPS_MAX):
            hub.home.create_group(con, X, f"g{i}")
        with pytest.raises(ValueError, match="30"):
            hub.home.create_group(con, X, "en til")
        assert len(hub.home.get_groups(con, X)) == 30
        hub.home.delete_group(con, X, hub.home.get_groups(con, X)[0]["id"])
        hub.home.create_group(con, X, "en til")


def test_constants(hub):
    assert hub.home.GROUP_NAME_MAX == 40 and hub.home.GROUPS_MAX == 30


def test_unknown_group_is_keyerror(hub):
    with hub.db() as con:
        for call in (
            lambda: hub.home.rename_group(con, X, "nope", "A"),
            lambda: hub.home.delete_group(con, X, "nope"),
            lambda: hub.home.set_app_group(con, X, "a", "nope"),
            lambda: hub.home.set_group_apps(con, X, "nope", ["a"]),
            lambda: hub.home.set_group_open(con, X, "nope", False),
        ):
            with pytest.raises(KeyError):
                call()
        gid = hub.home.create_group(con, X, "A")["id"]
        with pytest.raises(KeyError):  # someone else's group
            hub.home.rename_group(con, "y@t.no", gid, "B")
        hub.home.set_app_group(con, X, "a", gid)
        with pytest.raises(KeyError):  # the unknown id is checked before the app leaves its group
            hub.home.set_app_group(con, X, "a", "nope")
        assert hub.home.get_groups(con, X)[0]["slugs"] == ["a"]


def test_create_with_slug_moves_the_app(hub):
    with hub.db() as con:
        a = hub.home.create_group(con, X, "A")
        hub.home.set_app_group(con, X, "s", a["id"])
        b = hub.home.create_group(con, X, "B", "s")
        assert b["slugs"] == ["s"]
        assert [g["slugs"] for g in hub.home.get_groups(con, X)] == [[], ["s"]]


def test_set_app_group_moves_between_groups_and_out(hub):
    a, b = _mk(hub, "A", "B")
    with hub.db() as con:
        def view():  # inside the open transaction
            return {g["id"]: g["slugs"] for g in hub.home.get_groups(con, X)}

        hub.home.set_app_group(con, X, "s1", a)
        hub.home.set_app_group(con, X, "s2", a)
        hub.home.set_app_group(con, X, "s1", b)
        assert view() == {a: ["s2"], b: ["s1"]}
        hub.home.set_app_group(con, X, "s3", b)  # a new app goes last
        hub.home.set_app_group(con, X, "s2", b)
        assert view() == {a: [], b: ["s1", "s3", "s2"]}
        hub.home.set_app_group(con, X, "s1", b)  # same group: moves to the end
        assert view()[b] == ["s3", "s2", "s1"]
        hub.home.set_app_group(con, X, "s3", None)
        assert view()[b] == ["s2", "s1"]
        hub.home.set_app_group(con, X, "nowhere", None)  # not in any group: nothing happens
        assert view()[b] == ["s2", "s1"]


def test_delete_group_leaves_its_apps_ungrouped(hub):
    a, b = _mk(hub, "A", "B")
    with hub.db() as con:
        hub.home.set_app_group(con, X, "s1", a)
        hub.home.set_app_group(con, X, "s2", b)
        hub.home.delete_group(con, X, a)
    assert _view(hub) == {b: ["s2"]}


def test_set_group_apps_merges_like_pins(hub):
    (a,) = _mk(hub, "A")
    with hub.db() as con:
        for s in "abc":
            hub.home.set_app_group(con, X, s, a)
        assert hub.home.set_group_apps(con, X, a, ["c", "zz", "a", "c"]) == ["c", "a", "b"]
        assert hub.home.set_group_apps(con, X, a, []) == ["c", "a", "b"]
    assert _view(hub)[a] == ["c", "a", "b"]


def test_stale_app_order_does_not_move_apps_between_groups(hub):
    # Review Focus 1: the page was opened before "b" moved to the other group.
    a, b = _mk(hub, "A", "B")
    with hub.db() as con:
        for s in "abc":
            hub.home.set_app_group(con, X, s, a)
        hub.home.set_app_group(con, X, "b", b)
        assert hub.home.set_group_apps(con, X, a, ["c", "b", "a"]) == ["c", "a"]
    assert _view(hub) == {a: ["c", "a"], b: ["b"]}


def test_stale_group_order_does_not_bring_back_a_deleted_group(hub):
    # Review Focus 1: the page was opened before group "b" was deleted.
    a, b, c = _mk(hub, "A", "B", "C")
    with hub.db() as con:
        hub.home.set_app_group(con, X, "s", b)
        hub.home.delete_group(con, X, b)
        assert hub.home.set_group_order(con, X, [c, b, "nope", a, c]) == [c, a]
    assert [g["id"] for g in _groups(hub)] == [c, a]
    assert [g["slugs"] for g in _groups(hub)] == [[], []]


def test_set_group_order_keeps_groups_left_out(hub):
    a, b, c = _mk(hub, "A", "B", "C")
    with hub.db() as con:
        # Only c was shown: nothing it could pass, so nothing moves
        assert hub.home.set_group_order(con, X, [c]) == [a, b, c]
    assert [g["id"] for g in _groups(hub)] == [a, b, c]


def test_hidden_apps_keep_their_place_in_a_group(hub):
    # The page shows only some of a group (b is pinned, or not on the front page): a drop sends d, a, c, and b
    # stays right after a instead of drifting to the end
    (g,) = _mk(hub, "G")
    with hub.db() as con:
        for s in "abcd":
            hub.home.set_app_group(con, X, s, g)
        assert hub.home.set_group_apps(con, X, g, ["d", "a", "c"]) == ["d", "a", "b", "c"]
        # a and b left out: they go with d, the shown app they followed
        assert hub.home.set_group_apps(con, X, g, ["c", "d"]) == ["c", "d", "a", "b"]


def test_a_hidden_first_app_stays_first(hub):
    (g,) = _mk(hub, "G")
    with hub.db() as con:
        for s in "xabc":
            hub.home.set_app_group(con, X, s, g)
        assert hub.home.set_group_apps(con, X, g, ["c", "a", "b"]) == ["x", "c", "a", "b"]
        # still only the group's own slugs, each once (Review Focus 1)
        assert hub.home.set_group_apps(con, X, g, ["b", "zz", "b", "a"]) == ["x", "c", "b", "a"]


def test_an_empty_group_keeps_its_place_in_the_group_order(hub):
    # Empty groups are not on the front page, so a drop of the groups leaves them out
    a, empty, b, c = _mk(hub, "A", "Empty", "B", "C")
    with hub.db() as con:
        assert hub.home.set_group_order(con, X, [c, a, b]) == [c, a, empty, b]
        assert hub.home.set_group_order(con, X, [b, c]) == [b, c, a, empty]
    assert [g["id"] for g in _groups(hub)] == [b, c, a, empty]


def test_set_group_open(hub):
    a, b = _mk(hub, "A", "B")
    with hub.db() as con:
        hub.home.set_group_open(con, X, a, False)
    assert [g["open"] for g in _groups(hub)] == [False, True]
    with hub.db() as con:
        hub.home.set_group_open(con, X, a, True)
    assert [g["open"] for g in _groups(hub)] == [True, True]


def test_get_groups_drops_junk(hub):
    for junk in ("x", 5, None, {"id": "a"}, [{"id": 1}], ["x", 3, None]):
        _store(hub, X, junk)
        assert _groups(hub) == []
    _store(hub, X, [
        {"id": 1, "name": "bad id", "slugs": [], "open": True},
        {"id": "", "name": "empty id", "slugs": [], "open": True},
        {"id": "n", "name": 5, "slugs": [], "open": True},
        {"id": "e", "name": "  ", "slugs": [], "open": True},
        {"id": "a", "name": "A", "slugs": ["s1", 7, "s2", "s1", None], "open": False},
        {"id": "a", "name": "again", "slugs": ["s9"], "open": True},          # a repeated id
        {"id": "b", "name": "B", "slugs": ["s2", "s3"], "open": "yes"},       # s2 stays in the first group
        {"id": "c", "name": "C", "slugs": "s4"},
        "junk",
    ])
    assert _groups(hub) == [
        {"id": "a", "name": "A", "slugs": ["s1", "s2"], "open": False},
        {"id": "b", "name": "B", "slugs": ["s3"], "open": True},
        {"id": "c", "name": "C", "slugs": [], "open": True},
    ]


def test_unparseable_stored_groups_are_not_fatal(hub):
    with hub.db() as con:
        con.execute("INSERT INTO prefs(email, key, value) VALUES(?,?,?)", (X, "groups", "{not json"))
        assert hub.home.get_groups(con, X) == []


def test_rename_app_keeps_it_in_its_group(hub):
    # Review Focus 2
    a, b = _mk(hub, "A", "B")
    with hub.db() as con:
        for s in ("a", "x"):
            hub.home.set_app_group(con, X, s, a)
        hub.home.set_app_group(con, X, "m", b)
        hub.home.set_app_group(con, "y@t.no", "a", hub.home.create_group(con, "y@t.no", "Y")["id"])
        hub.home.set_app_group(con, X, "k", b)
        hub.home.rename(con, "a", "b")
    assert _view(hub) == {a: ["b", "x"], b: ["m", "k"]}
    assert [g["slugs"] for g in _groups(hub, "y@t.no")] == [["b"]]


def test_rename_leaves_groups_alone_when_the_app_is_in_none(hub):
    (a,) = _mk(hub, "A")
    with hub.db() as con:
        hub.home.set_app_group(con, X, "x", a)
        before = con.execute("SELECT value FROM prefs WHERE email=? AND key='groups'", (X,)).fetchone()["value"]
        hub.home.rename(con, "a", "b")
        after = con.execute("SELECT value FROM prefs WHERE email=? AND key='groups'", (X,)).fetchone()["value"]
    assert before == after


def _others(con):
    """Every stored pref except the groups."""
    return [tuple(r) for r in con.execute(
        "SELECT key, value FROM prefs WHERE email=? AND key!='groups' ORDER BY key", (X,)).fetchall()]


def test_groups_never_touch_the_other_prefs(hub):
    with hub.db() as con:
        for s in ("a", "b"):
            hub.home.set_added(con, X, s, True)
            hub.home.set_pin(con, X, s, True)
        hub.home.set_view(con, X, "cards")
        before = _others(con)
        assert len(before) == 4  # apps, pins, seen, view
        g = hub.home.create_group(con, X, "A", "a")["id"]
        h = hub.home.create_group(con, X, "B")["id"]
        hub.home.rename_group(con, X, g, "C")
        hub.home.set_app_group(con, X, "b", g)
        hub.home.set_app_group(con, X, "a", h)
        hub.home.set_group_apps(con, X, g, ["b"])
        hub.home.set_group_order(con, X, [h, g])
        hub.home.set_group_open(con, X, g, False)
        hub.home.set_app_group(con, X, "a", None)
        hub.home.delete_group(con, X, h)
        assert _others(con) == before
        hub.home.rename(con, "a", "z")  # only the rename rewrites them, as it always did
        assert hub.home.get_prefs(con, X)["apps"] == ["z", "b"]


# ---------------------------------------------------------------- routes
def _page(hub, slug="a", **kw):
    hub.save_page(slug, PAGE, create=True, private=False, **kw)


def _post(client, route, **body):
    return client.post(f"/api/prefs/groups/{route}", json=body)


def _gid(r):
    return r.json()["groups"][-1]["id"]


def test_routes_answer_ok_and_the_groups(hub, user_client):
    for s in ("a", "b"):
        _page(hub, s)
    r = _post(user_client, "new", name=" Jobb ")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and [g["name"] for g in body["groups"]] == ["Jobb"] and body["groups"][0]["open"] is True
    g1 = _gid(r)
    r = _post(user_client, "new", name="Fritid", slug="a")
    g2 = _gid(r)
    assert [g["slugs"] for g in r.json()["groups"]] == [[], ["a"]]
    assert _post(user_client, "app", slug="b", id=g2).json()["groups"][1]["slugs"] == ["a", "b"]
    assert _post(user_client, "apps", id=g2, order=["b", "a"]).json()["groups"][1]["slugs"] == ["b", "a"]
    assert _post(user_client, "app", slug="b", id=None).json()["groups"][1]["slugs"] == ["a"]
    assert [g["id"] for g in _post(user_client, "order", order=[g2, g1]).json()["groups"]] == [g2, g1]
    r = _post(user_client, "open", id=g2, open=False)
    assert r.json() == {"ok": True, "groups": [
        {"id": g2, "name": "Fritid", "slugs": ["a"], "open": False},
        {"id": g1, "name": "Jobb", "slugs": [], "open": True}]}
    assert _post(user_client, "rename", id=g1, name="Arbeid").json()["groups"][1]["name"] == "Arbeid"
    r = _post(user_client, "delete", id=g2)
    assert r.json() == {"ok": True, "groups": [{"id": g1, "name": "Arbeid", "slugs": [], "open": True}]}
    assert _groups(hub, "user@test.no") == r.json()["groups"]


def test_routes_answer_400_for_bad_input(hub, user_client):
    _page(hub)
    gid = _gid(_post(user_client, "new", name="A"))
    bad = [
        ("new", {}), ("new", {"name": 5}), ("new", {"name": ""}), ("new", {"name": "x" * 41}),
        ("new", {"name": "a"}),  # taken, ignoring case
        ("new", {"name": "B", "slug": 5}),
        ("rename", {"id": gid}), ("rename", {"id": 5, "name": "B"}), ("rename", {"id": gid, "name": " "}),
        ("rename", {"id": gid, "name": "X" * 41}),
        ("delete", {}), ("delete", {"id": 5}),
        ("app", {}), ("app", {"slug": 5, "id": gid}), ("app", {"slug": "a"}), ("app", {"slug": "a", "id": 5}),
        ("apps", {"id": gid}), ("apps", {"id": gid, "order": "a"}), ("apps", {"id": gid, "order": [1]}),
        ("apps", {"order": []}),
        ("order", {}), ("order", {"order": "a"}), ("order", {"order": [1]}),
        ("open", {"id": gid}), ("open", {"id": gid, "open": "no"}), ("open", {"open": True}),
    ]
    for route, body in bad:
        assert _post(user_client, route, **body).status_code == 400, (route, body)
    for route in ("new", "rename", "delete", "app", "apps", "order", "open"):
        r = user_client.post(f"/api/prefs/groups/{route}", json=["not", "an", "object"])
        assert r.status_code == 400, route
    r = _post(user_client, "new", name="")
    assert "1–40" in r.json()["detail"]
    assert [g["name"] for g in _groups(hub, "user@test.no")] == ["A"]


def test_routes_answer_404_for_unknown_group_or_unseen_app(hub, user_client):
    _page(hub, "a")
    hub.save_page("hemmelig", PAGE, create=True, private=True)
    gid = _gid(_post(user_client, "new", name="A"))
    for route, body in [
        ("rename", {"id": "nope", "name": "B"}), ("delete", {"id": "nope"}),
        ("app", {"slug": "a", "id": "nope"}), ("apps", {"id": "nope", "order": []}),
        ("open", {"id": "nope", "open": True}),
        ("app", {"slug": "finnes-ikke", "id": gid}), ("app", {"slug": "hemmelig", "id": gid}),
        ("app", {"slug": "hemmelig", "id": None}),
        ("new", {"name": "B", "slug": "finnes-ikke"}), ("new", {"name": "B", "slug": "hemmelig"}),
    ]:
        assert _post(user_client, route, **body).status_code == 404, (route, body)
    assert [g["name"] for g in _groups(hub, "user@test.no")] == ["A"]  # the failed "new" created nothing


def test_routes_need_login_and_json(hub, user_client, client):
    for route in ("new", "rename", "delete", "app", "apps", "order", "open"):
        assert _post(client, route).status_code == 401, route
        assert user_client.post(f"/api/prefs/groups/{route}", data={"name": "A"}).status_code == 415, route


def test_routes_are_per_user(hub, user_client, admin_client):
    gid = _gid(_post(user_client, "new", name="A"))
    assert _post(admin_client, "rename", id=gid, name="B").status_code == 404
    assert _post(admin_client, "new", name="A").status_code == 200


def test_routes_leave_apps_pins_and_seen_alone(hub, user_client):
    for s in ("a", "b"):
        _page(hub, s)
        user_client.post("/api/prefs/apps", json={"slug": s, "added": True})
        user_client.post("/api/prefs/pin", json={"slug": s, "pinned": True})
    user_client.post("/api/prefs/seen", json={})
    with hub.db() as con:
        before = hub.home.get_prefs(con, "user@test.no")
    g = _gid(_post(user_client, "new", name="A", slug="a"))
    h = _gid(_post(user_client, "new", name="B"))
    _post(user_client, "app", slug="b", id=g)
    _post(user_client, "apps", id=g, order=["b", "a"])
    _post(user_client, "order", order=[h, g])
    _post(user_client, "open", id=g, open=False)
    _post(user_client, "rename", id=h, name="C")
    _post(user_client, "app", slug="a", id=None)
    _post(user_client, "delete", id=g)
    with hub.db() as con:
        assert hub.home.get_prefs(con, "user@test.no") == before
    assert json.dumps(before)  # sanity: a real, non-empty prefs dict
    assert before["apps"] == ["a", "b"] and before["pins"] == ["a", "b"] and before["seen"]


def test_markup_in_a_name_is_stored_as_typed(hub, user_client):
    r = _post(user_client, "new", name='<b>x</b> "q" & co')
    assert r.json()["groups"][0]["name"] == '<b>x</b> "q" & co'


def test_two_changes_at_the_same_moment_both_survive(hub, user_client, monkeypatch):
    """A fold arrives while a drag-save is half done: it must wait, not be overwritten (one JSON value holds all groups)."""
    import threading

    user = "user@test.no"
    with hub.db() as con:  # the test user's own groups
        g1 = hub.home.create_group(con, user, "A")["id"]
        g2 = hub.home.create_group(con, user, "B")["id"]
    real, state = hub.home.get_groups, {"first": True, "waited": None}
    other = threading.Thread(target=lambda: state.setdefault(
        "status", make_client(user).post("/api/prefs/groups/open", json={"id": g2, "open": False}).status_code))

    def get_groups(con, email):
        groups = real(con, email)  # read by the drag-save...
        if state["first"]:
            state["first"] = False
            other.start()  # ...then the fold is sent from another connection
            other.join(1)
            state["waited"] = other.is_alive()  # with the lock it is still waiting; without it, it has already written
        return groups

    monkeypatch.setattr(hub.home, "get_groups", get_groups)
    r = _post(user_client, "order", order=[g2, g1])
    other.join(10)
    monkeypatch.undo()
    assert r.status_code == 200 and state["status"] == 200 and state["waited"] is True
    assert [(g["id"], g["open"]) for g in _groups(hub, user)] == [(g2, False), (g1, True)]


def test_malformed_json_is_400_on_the_group_routes(hub, user_client):
    for route in ("new", "rename", "delete", "app", "apps", "order", "open"):
        r = user_client.post(f"/api/prefs/groups/{route}", content=b"{nope", headers={"content-type": "application/json"})
        assert r.status_code == 400, route
        r = user_client.post(f"/api/prefs/groups/{route}", content=b"\xff\xfe", headers={"content-type": "application/json"})
        assert r.status_code == 400, route


# ---------------------------------------------------------------- the front page
U = "user@test.no"


def _front(hub, *slugs):
    """Public apps `slugs` on user@test.no's front page (title = upper-case slug)."""
    for s in slugs:
        _page(hub, s, title=s.upper())
    with hub.db() as con:
        for s in slugs:
            hub.home.set_added(con, U, s, True)


def _grp(hub, name, slugs=(), open_=True):
    with hub.db() as con:
        g = hub.home.create_group(con, U, name)
        for s in slugs:
            hub.home.set_app_group(con, U, s, g["id"])
        if not open_:
            hub.home.set_group_open(con, U, g["id"], False)
    return g["id"]


def _sec(html, sid):
    start = html.find(f'<section id="{sid}"')
    return "" if start < 0 else html[start:html.find("</section>", start)]


def test_rest_is_all_apps_without_groups(hub, user_client):
    _front(hub, "a", "b")
    html = user_client.get("/").text
    assert 'class="group"' not in html and 'data-group=' not in html
    with hub.db() as con:
        hub.home.set_pin(con, U, "a", True)
    rest = _sec(user_client.get("/").text, "rest")
    assert "Alle apper" in rest and "Andre" not in rest


def test_rest_is_other_when_groups_exist(hub, user_client):
    _front(hub, "a", "b")
    _grp(hub, "Jobb", ["a"])
    html = user_client.get("/").text
    rest = _sec(html, "rest")
    assert "Andre" in rest and "Alle apper" not in rest and 'data-slug="b"' in rest and 'data-slug="a"' not in rest
    assert html.index('class="group"') < html.index('id="rest"')


def test_rest_is_other_when_every_group_is_hidden(hub, user_client):
    _front(hub, "a")
    _grp(hub, "Tom")  # no apps: not shown, but the user has a group
    html = user_client.get("/").text
    assert 'data-group=' not in html and "Andre" in _sec(html, "rest")


def test_no_rest_heading_when_every_app_is_grouped_or_pinned(hub, user_client):
    _front(hub, "a", "b")
    _grp(hub, "Jobb", ["a"])
    with hub.db() as con:
        hub.home.set_pin(con, U, "b", True)
    html = user_client.get("/").text
    front = html[:html.index("<dialog")]
    rest = _sec(front, "rest")
    assert rest and "<ul" in rest  # kept for the offline layout and the refresh
    assert "Andre" not in front and "Alle apper" not in front and 'class="sec"' not in rest


def test_group_markup_open(hub, user_client):
    _front(hub, "a", "b", "c")
    gid = _grp(hub, "Jobb", ["b", "a"])
    html = user_client.get("/").text
    sec = _sec(html, f"g-{gid}")
    assert f'<section id="g-{gid}" class="group" data-group="{gid}" data-order="group" data-open="1">' in sec
    assert '<h3 class="sec"><button type="button" class="gtoggle" aria-expanded="true" data-label="Åpne eller lukk Jobb">' in sec
    assert 'Jobb<span class="gcount">· 2</span><span class="chev"></span></button></h3>' in sec
    assert sec.index('data-slug="b"') < sec.index('data-slug="a"') and 'data-slug="c"' not in sec
    assert "hidden" not in sec and "gclosed" not in sec


def test_closed_group_markup(hub, user_client):
    _front(hub, "a", "b", "c")
    gid = _grp(hub, "Jobb", ["a", "b"], open_=False)
    sec = _sec(user_client.get("/").text, f"g-{gid}")
    assert 'data-open="0"' in sec and 'aria-expanded="false"' in sec and '<span class="gcount">· 2</span>' in sec
    assert '<ul class="cards" hidden>' in sec and 'data-slug="a"' in sec  # still rendered, only hidden
    assert "gclosed" not in sec
    grid = sec[sec.index('<div class="gicons">'):]
    assert grid.count('<a class="gicon" href="/a/') == 2 and grid.count('class="icon"') == 2
    assert grid.count('aria-hidden="true"') == 2  # a screen reader gets the name, not the letters
    assert '<a class="gicon" href="/a/a/" data-slug="a">' in grid and "<span>A</span>" in grid
    head = sec[sec.index('class="gtoggle"'):sec.index("</h3>")]
    assert 'data-label="Åpne eller lukk Jobb"' in head and "aria-label" not in head  # named by its text and count


def test_closed_group_names_are_escaped_in_the_heading_label(hub, user_client):
    _front(hub, "a")
    gid = _grp(hub, '<b>x</b>"&', ["a"], open_=False)
    sec = _sec(user_client.get("/").text, f"g-{gid}")
    assert 'data-label="Åpne eller lukk &lt;b&gt;x&lt;/b&gt;&#34;&amp;"' in sec and "<b>x</b>" not in sec


def test_closed_group_keeps_its_lines_in_the_hidden_list(hub, user_client):
    _front(hub, "a")
    gid = _grp(hub, "Jobb", ["a"], open_=False)
    with hub.db() as con:
        hub.home.set_view(con, U, "cards")
    sec = _sec(user_client.get("/").text, f"g-{gid}")
    assert '<ul class="cards" hidden>' in sec and 'class="gicons"' in sec


def test_pinned_app_is_not_in_its_group_on_the_page(hub, user_client):
    _front(hub, "a", "b")
    gid = _grp(hub, "Jobb", ["a", "b"])
    with hub.db() as con:
        hub.home.set_pin(con, U, "a", True)
    html = user_client.get("/").text
    assert 'data-slug="a"' in _sec(html, "fav") and 'data-slug="a"' not in _sec(html, f"g-{gid}")
    assert '<span class="gcount">· 1</span>' in _sec(html, f"g-{gid}")
    assert html[: html.index("<dialog")].count('<li class="app pinned" data-slug="a"') == 1  # the picker below lists every app


def test_gone_apps_not_shown_or_counted(hub, user_client):
    _front(hub, "a", "b")
    gid = _grp(hub, "Jobb", ["a", "b", "slettet"], open_=False)
    sec = _sec(user_client.get("/").text, f"g-{gid}")
    assert "slettet" not in sec and '<span class="gcount">· 2</span>' in sec
    assert sec.count('<a class="gicon"') == 2
    with hub.db() as con:  # access lost: still in the stored group, not on the page
        hub.home.set_added(con, U, "b", False)
    sec = _sec(user_client.get("/").text, f"g-{gid}")
    assert 'data-slug="b"' not in sec and '<span class="gcount">· 1</span>' in sec
    assert sec.count('<a class="gicon"') == 1


def test_group_with_only_gone_apps_is_not_shown(hub, user_client):
    _front(hub, "a")
    gid = _grp(hub, "Jobb", ["slettet"])
    html = user_client.get("/").text
    front = html[:html.index("<dialog")]
    assert "Jobb" not in front and 'data-group=' not in front
    assert "<h2>Jobb</h2>" in _pgroup(_picker(html), gid)  # still there to arrange


def test_group_name_escaped(hub, user_client):
    _front(hub, "a")
    name = '<b>x</b>"&'
    gid = _grp(hub, name, ["a"])
    html = user_client.get("/").text
    sec = _sec(html, f"g-{gid}")
    assert "&lt;b&gt;x&lt;/b&gt;&#34;&amp;" in sec and "<b>x</b>" not in html
    assert 'data-label="Åpne eller lukk &lt;b&gt;x&lt;/b&gt;&#34;&amp;"' in sec


# ---------------------------------------------------------------- folding (home.js, hub.css)
def _static(name):
    return (Path(__file__).resolve().parent.parent / "app" / "static" / name).read_text("utf-8")


def test_fold_wiring():
    js, css = _static("home.js"), _static("hub.css")
    for needle in ("gtoggle", "gclosed", "/api/prefs/groups/open", "toggleGroup", "hubDragJustEnded"):
        assert needle in js
    for needle in (".gclosed", ".gtoggle", '.group[data-open="0"]'):
        assert needle in css


def test_offline_layout_collects_every_group():
    js = _static("home.js")
    start = js.index("async function enterOffline")
    body = js[start:js.index("if (offline()) enterOffline()", start)]
    assert "section.group" in body and '"top"' not in body and "#top" not in body
    assert "#top" not in js


# ---------------------------------------------------------------- hold and drag (drag.js)
def test_drag_wiring():
    js, home, css = _static("drag.js"), _static("home.js"), _static("hub.css")
    for needle in ("data-order", "/api/prefs/pins", "/api/prefs/groups/apps", "/api/prefs/groups/order",
                   "hubDragJustEnded", ".gtoggle"):
        assert needle in js
    # Not only the favourites any more: every ordered section, and the menu's long press is drag.js's in all of them
    assert "#fav .app" not in js and "#fav ul" not in js
    assert 'closest("#fav")' not in home
    assert ".group.lifted" in css and ".group.sliding" in css


# ---------------------------------------------------------------- «Ordne apper» (the sheet)
def _picker(html):
    """The sheet as drawn, without the empty heading home.js copies for a new group."""
    return html[html.find('id="picker"'):html.find('<template id="pgroupNew">')]


def _pgroup(p, gid=""):
    """The sheet's section for group `gid` ("" = no group)."""
    start = p.find(f'<section class="pgroup" data-gid="{gid}"')
    return "" if start < 0 else p[start:p.find("</section>", start)]


def test_picker_grouped(hub):
    apps = [{"slug": s, "title": s.upper(), "updated": 0} for s in ("a", "b", "c", "d", "e")]
    groups = [{"id": "g1", "name": "Jobb", "slugs": ["d", "slettet", "b"], "open": True},
              {"id": "g2", "name": "Tom", "slugs": [], "open": False},
              {"id": "g3", "name": "Les", "slugs": ["a"], "open": True}]
    out = hub.home.picker(apps, ["a", "b"], ["a", "b", "c"], groups)
    assert [(g and g["id"], [a["slug"] for a in rows]) for g, rows in out] == [
        ("g1", ["d", "b"]), ("g2", []), ("g3", ["a"]), (None, ["c", "e"])]  # unseen e is not lifted first any more
    marks = {a["slug"]: (a["added"], a["unseen"]) for _, rows in out for a in rows}
    assert marks == {"a": (True, False), "b": (True, False), "c": (False, False), "d": (False, True), "e": (False, True)}
    assert [(g, [a["slug"] for a in rows]) for g, rows in hub.home.picker(apps[:2], [], None, [])] == [(None, ["a", "b"])]


def test_picker_grouped_on_the_page(hub, user_client):
    _front(hub, "a", "b", "c")
    jobb = _grp(hub, "Jobb", ["c", "a"])
    tom = _grp(hub, "Tom")
    _page(hub, "d", title="D")  # not on the front page, never seen: «Ny», in its group
    with hub.db() as con:
        hub.home.set_app_group(con, U, "d", jobb)
        hub.home.set_pin(con, U, "a", True)  # pinned: still listed under its group in the sheet
    p = _picker(user_client.get("/").text)
    g, empty, rest = _pgroup(p, jobb), _pgroup(p, tom), _pgroup(p)
    assert p.index(g) < p.index(empty) < p.index(rest)
    assert g.index('data-slug="c"') < g.index('data-slug="a"') < g.index('data-slug="d"')
    assert "<h2>Uten gruppe</h2>" in rest and 'data-slug="b"' in rest and "data-slug" not in empty
    assert g.count(">Ny<") == 1 and ">Ny<" in g[g.index('data-slug="d"'):]


def test_picker_markup(hub, user_client):
    _front(hub, "a", "b")
    gid = _grp(hub, "Jobb", ["a"])
    html = user_client.get("/").text
    assert '<button type="button" class="more" data-open-picker>＋ Ordne apper' in html
    p = _picker(html)
    assert '<h1 id="pickerTitle" tabindex="-1" autofocus>Ordne apper</h1>' in p
    assert "Huk av det du vil ha på forsiden, og velg gruppe." in p
    assert p.count('class="gpick"') == 2 and p.count('class="grename"') == p.count('class="gdelete"') == 1
    assert p.count('class="gnew"') == 1 and "Ny gruppe" in p[p.index('class="gnew"'):]
    g, rest = _pgroup(p, gid), _pgroup(p)
    assert "<h2>Jobb</h2>" in g and 'class="grename"' in g and 'class="gdelete"' in g
    assert 'class="grename"' not in rest and 'class="gdelete"' not in rest
    pick = lambda sec: sec[sec.index('class="gpick"'):sec.index("</button>", sec.index('class="gpick"'))]  # noqa: E731
    assert ">Jobb<" in pick(g) and ">Velg gruppe<" in pick(rest)
    assert 'aria-haspopup="menu"' in pick(g) and 'aria-expanded="false"' in pick(g)
    assert "<select" not in html


def test_picker_without_groups_hides_the_no_group_heading(hub, user_client):
    _front(hub, "a")
    p = _picker(user_client.get("/").text)
    assert '<section class="pgroup" data-gid="" hidden>' not in p  # the list itself shows
    assert 'class="gnew"' in p and 'class="grename"' not in p
    assert '<div class="gh" hidden><h2>Uten gruppe</h2>' in _pgroup(p)


def test_picker_name_escaped(hub, user_client):
    _front(hub, "a")
    gid = _grp(hub, '<b>x</b>"&', ["a"])
    p = _picker(user_client.get("/").text)
    esc = "&lt;b&gt;x&lt;/b&gt;&#34;&amp;"
    g = _pgroup(p, gid)
    assert f"<h2>{esc}</h2>" in g and f'<span class="gchip">{esc}</span>' in g  # the heading and the row's button
    assert f'aria-label="A: {esc}"' in g
    assert f'aria-label="Gi nytt navn: {esc}"' in g and f'aria-label="Slett: {esc}"' in g
    assert "<b>x</b>" not in p
    # The page draws names into the sheet and the menu itself: only ever as text
    js = _static("home.js")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML =" not in js
    assert "prompt(" not in js and "confirm(" not in js


def test_picker_wiring():
    js, css = _static("home.js"), _static("hub.css")
    for needle in ("/api/prefs/groups/new", "/api/prefs/groups/rename", "/api/prefs/groups/delete",
                   "/api/prefs/groups/app", ".gpick", ".grename", ".gdelete", ".gnew", "group_delete_ask"):
        assert needle in js
    for needle in ("#picker .gpick", "#picker .gmenu", "#picker .gform"):
        assert needle in css


def test_picker_guards_double_taps_and_order():
    js = _static("home.js")
    body = js[js.index("«Arrange apps»"):]
    # one chain for every group request, so answers are drawn in the order they were asked
    for route in ("/api/prefs/groups/app", "/api/prefs/groups/new", "/api/prefs/groups/rename", "/api/prefs/groups/delete"):
        assert f'inTurn("{route}"' in body or "inTurn(url" in body
    assert 'send("/api/prefs/groups/' not in body
    assert "aria-busy" in body and "tabIndex = -1" in body and "deleting" in body
