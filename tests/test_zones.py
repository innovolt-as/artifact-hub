"""Zone rules for logged-in users (app/public.py): admins reach every user's agent zone in an app with "agent", and
the owner of a guest zone reads it only without "guests_hidden", never writes in it and may always delete by path."""
import json

import pytest

from tests.conftest import make_client
from tests.test_public_settings import add_guest_docs
from tests.test_shared_data import get, ids, make_shared, put

ADMIN, U = "admin@test.no", "user@test.no"
AGENT = f"data/users/{U}/agent"
GUESTS = f"data/users/{U}/guests/main"


def make_zoned(hub, make_page, slug="radar", **settings):
    make_shared(hub, make_page, slug)
    if settings:
        hub.set_public(slug, **settings)


def rows(hub, slug="radar"):
    with hub.db() as con:
        return con.execute("SELECT owner, collection, doc_id FROM docs WHERE slug=? ORDER BY collection, doc_id",
                           (slug,)).fetchall()


def delete(c, slug, path):
    return c.delete(f"/api/store/{slug}/d", params={"path": path})


# ---------------------------------------------------------------- the agent zone
def test_admin_reads_and_writes_other_users_agent_zone(hub, make_page, admin_client, user_client):
    make_zoned(hub, make_page, agent=True)
    assert put(user_client, "radar", f"{AGENT}/track/w1", {"want": "sykkel"}).status_code == 200
    assert get(admin_client, "radar", f"{AGENT}/track/w1") == {"want": "sykkel"}
    assert get(admin_client, "radar", "data/users/User@Test.no/agent/track/w1") == {"want": "sykkel"}
    assert ids(admin_client, "radar", f"{AGENT}/track") == ["w1"]
    assert put(admin_client, "radar", f"{AGENT}/match/w1", {"price": 100}).status_code == 200
    assert put(admin_client, "radar", f"{AGENT}/match/w1", {"shop": "x"}, merge="true").status_code == 200
    assert get(user_client, "radar", f"{AGENT}/match/w1") == {"price": 100, "shop": "x"}
    # the same through the connector's helpers
    assert hub.doc_get("radar", ADMIN, f"{AGENT}/track/w1") == {"want": "sykkel"}
    assert hub.doc_list("radar", ADMIN, f"{AGENT}/track") == {"w1": {"want": "sykkel"}}
    hub.doc_set("radar", ADMIN, f"{AGENT}/match/w2", {"price": 5})
    assert hub.doc_get("radar", U, f"{AGENT}/match/w2") == {"price": 5}
    assert hub.doc_delete("radar", ADMIN, f"{AGENT}/match/w2") is True
    assert delete(admin_client, "radar", f"{AGENT}/match/w1").status_code == 200
    # every row stays the user's
    assert {r["owner"] for r in rows(hub)} == {U}
    assert [(r["collection"], r["doc_id"]) for r in rows(hub)] == [(f"{AGENT}/track", "w1")]


def test_admin_still_cannot_read_rest_of_branch(hub, make_page, admin_client, user_client):
    make_zoned(hub, make_page, agent=True)
    put(user_client, "radar", f"data/users/{U}/wishes/jul/w1", {"x": 1})
    put(user_client, "radar", f"data/users/{U}/agent", {"x": 2})  # the document "agent" is not in the zone
    put(user_client, "radar", f"data/users/{U}/agentx/track/w1", {"x": 3})
    for path in (f"data/users/{U}/wishes/jul/w1", f"data/users/{U}/agent", f"data/users/{U}/agentx/track/w1"):
        assert get(admin_client, "radar", path) is None
        assert hub.doc_get("radar", ADMIN, path) is None
        assert put(admin_client, "radar", path, {"x": 9}).status_code == 403
        assert delete(admin_client, "radar", path).status_code == 403
        with pytest.raises(hub.ReadOnly):
            hub.doc_set("radar", ADMIN, path, {"x": 9})
    assert ids(admin_client, "radar", f"data/users/{U}") == []
    assert get(user_client, "radar", f"data/users/{U}/wishes/jul/w1") == {"x": 1}


def test_non_admin_cannot_reach_another_users_agent_zone(hub, make_page, user_client):
    make_zoned(hub, make_page, agent=True)
    put(user_client, "radar", f"{AGENT}/track/w1", {"x": 1})
    assert hub.doc_get("radar", "venn@test.no", f"{AGENT}/track/w1") is None
    with pytest.raises(hub.ReadOnly):
        hub.doc_set("radar", "venn@test.no", f"{AGENT}/track/w1", {"x": 9})
    with hub.db() as con:
        assert hub.visible_docs(con, "radar", "venn@test.no") == []


def test_agent_zone_off_means_no_admin_access(hub, make_page, admin_client, user_client):
    for slug, settings in (("radar", {}), ("ting", {"public": True, "guests_hidden": True})):
        make_zoned(hub, make_page, slug, **settings)
        put(user_client, slug, f"{AGENT}/track/w1", {"x": 1})
        assert get(admin_client, slug, f"{AGENT}/track/w1") is None
        assert ids(admin_client, slug, f"{AGENT}/track") == []
        assert put(admin_client, slug, f"{AGENT}/track/w1", {"x": 9}).status_code == 403
        assert delete(admin_client, slug, f"{AGENT}/track/w1").status_code == 403
        assert admin_client.get(f"/api/store/{slug}").json() == {}
        assert get(user_client, slug, f"{AGENT}/track/w1") == {"x": 1}


def test_admin_dump_and_overview_include_agent_zones(hub, make_page, admin_client, user_client):
    make_zoned(hub, make_page, agent=True)
    put(admin_client, "radar", "briefs/b1", {"n": 1})
    put(user_client, "radar", f"{AGENT}/track/w1", {"x": 1})
    put(user_client, "radar", f"data/users/{U}/wishes/jul/w1", {"x": 2})
    put(admin_client, "radar", f"data/users/{ADMIN}/agent/track/a1", {"x": 3})
    want = {"briefs": {"b1": {"n": 1}}, f"{AGENT}/track": {"w1": {"x": 1}},
            f"data/users/{ADMIN}/agent/track": {"a1": {"x": 3}}}
    assert admin_client.get("/api/store/radar").json() == want
    assert hub.doc_overview("radar", ADMIN) == {k: list(v) for k, v in want.items()}
    assert user_client.get("/api/store/radar").json() == {  # the user sees their own branch, not the admin's zone
        "briefs": {"b1": {"n": 1}}, f"{AGENT}/track": {"w1": {"x": 1}},
        f"data/users/{U}/wishes/jul": {"w1": {"x": 2}}}


# ---------------------------------------------------------------- the guest zone, for its owner
def test_owner_cannot_read_hidden_guest_zone(hub, make_page, admin_client, user_client):
    make_zoned(hub, make_page, public=True, guests_hidden=True, agent=True)
    add_guest_docs(hub, "radar", U, "main", n=2)
    with hub.db() as con:  # a collection under a guest document is in the zone too
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,'n1','{}',0)",
                    ("radar", U, f"{GUESTS}/r0/notes"))
    put(user_client, "radar", f"data/users/{U}/wishes/jul/w1", {"x": 1})
    for path in (f"{GUESTS}/r0", "data/users/User@Test.no/guests/main/r0", f"{GUESTS}/r0/notes/n1"):
        assert get(user_client, "radar", path) is None
        assert hub.doc_get("radar", U, path) is None
    for col in (GUESTS, f"{GUESTS}/r0/notes"):
        assert ids(user_client, "radar", col) == []
        assert hub.doc_list("radar", U, col) == {}
    dump = user_client.get("/api/store/radar").json()
    assert dump == {f"data/users/{U}/wishes/jul": {"w1": {"x": 1}}}
    assert hub.doc_overview("radar", U) == {f"data/users/{U}/wishes/jul": ["w1"]}
    assert admin_client.get("/api/store/radar").json() == {}  # the agent zone never opens a guest zone
    assert get(admin_client, "radar", f"{GUESTS}/r0") is None


def test_owner_reads_guest_zone_when_not_hidden(hub, make_page, user_client):
    make_zoned(hub, make_page, public=True)
    add_guest_docs(hub, "radar", U, "main", n=2)
    assert get(user_client, "radar", f"{GUESTS}/r1") == {"i": 1}
    assert ids(user_client, "radar", GUESTS) == ["r0", "r1"]
    assert user_client.get("/api/store/radar").json() == {GUESTS: {"r0": {"i": 0}, "r1": {"i": 1}}}
    assert hub.doc_get("radar", U, f"{GUESTS}/r0") == {"i": 0}
    assert hub.doc_list("radar", U, GUESTS) == {"r0": {"i": 0}, "r1": {"i": 1}}


@pytest.mark.parametrize("hidden", [False, True])
def test_owner_cannot_create_guest_docs(hub, make_page, user_client, hidden):
    make_zoned(hub, make_page, public=True, guests_hidden=hidden)
    add_guest_docs(hub, "radar", U, "main")
    for path in (f"{GUESTS}/r0", f"{GUESTS}/new", f"{GUESTS}/r0/notes/n1", "data/users/User@Test.no/guests/x/new"):
        assert put(user_client, "radar", path, {"i": 9}).status_code == 403
        assert put(user_client, "radar", path, {"i": 9}, merge="true").status_code == 403
        for merge in (False, True):
            with pytest.raises(hub.ReadOnly):
                hub.doc_set("radar", U, path, {"i": 9}, merge=merge)
    assert [(r["collection"], r["doc_id"]) for r in rows(hub)] == [(GUESTS, "r0")]
    with hub.db() as con:
        assert json.loads(con.execute("SELECT data FROM docs").fetchone()[0]) == {"i": 0}


@pytest.mark.parametrize("hidden", [False, True])
def test_owner_deletes_guest_doc_blind(hub, make_page, user_client, hidden):
    make_zoned(hub, make_page, public=True, guests_hidden=hidden)
    add_guest_docs(hub, "radar", U, "main", n=2)
    assert delete(user_client, "radar", f"{GUESTS}/r0").status_code == 200
    assert hub.doc_delete("radar", U, f"{GUESTS}/r1") is True
    assert rows(hub) == []
    assert hub.doc_delete("radar", U, f"{GUESTS}/r1") is True  # blind: the answer never tells whether it was there


def test_zone_names_are_ordinary_without_the_switch(hub, make_page, admin_client, user_client):
    make_zoned(hub, make_page, agent=True)  # another zone on, but neither public sharing nor guests_hidden
    path = f"data/users/{U}/guests/x/y"
    assert put(user_client, "radar", path, {"n": 1}).status_code == 200
    assert put(user_client, "radar", path, {"m": 2}, merge="true").status_code == 200
    assert get(user_client, "radar", path) == {"n": 1, "m": 2}
    assert user_client.get("/api/store/radar").json() == {f"data/users/{U}/guests/x": {"y": {"n": 1, "m": 2}}}
    assert get(admin_client, "radar", path) is None
    assert delete(user_client, "radar", path).status_code == 200
    make_page("mat")  # personal data: the path is just a name
    assert put(user_client, "mat", path, {"n": 1}).status_code == 200
    assert get(user_client, "mat", path) == {"n": 1}


def test_email_with_underscore_percent_and_capitals(hub, make_page, admin_client):
    odd = "a_b%c@Test.no"
    assert admin_client.post("/api/people/invite", json={"email": odd}).status_code == 200
    c = make_client(odd)
    make_zoned(hub, make_page, public=True, guests_hidden=True, agent=True)
    low = odd.lower()
    assert put(c, "radar", f"data/users/{odd}/agent/track/w1", {"x": 1}).status_code == 200
    assert put(c, "radar", f"data/users/{odd}/wishes/jul/w1", {"x": 2}).status_code == 200
    add_guest_docs(hub, "radar", low, "main")
    for near in ("aXb@test.no", "aXbc@test.no"):  # "aXbc" is what a_b%c would match with LIKE
        hub.doc_set("radar", near, f"data/users/{near}/agent/track/w1", {"near": near})
        add_guest_docs(hub, "radar", near.lower(), "main")
        assert hub.doc_get("radar", near, f"data/users/{low}/agent/track/w1") is None
        assert hub.doc_get("radar", near, f"data/users/{low}/guests/main/r0") is None
        assert hub.doc_overview("radar", near) == {f"data/users/{near.lower()}/agent/track": ["w1"]}
    assert get(admin_client, "radar", "data/users/A_B%C@test.no/agent/track/w1") == {"x": 1}
    assert get(c, "radar", f"data/users/{low}/guests/main/r0") is None
    assert c.delete("/api/store/radar/d", params={"path": f"data/users/{odd}/guests/main/r0"}).status_code == 200
    assert c.get("/api/store/radar").json() == {f"data/users/{low}/agent/track": {"w1": {"x": 1}},
                                                f"data/users/{low}/wishes/jul": {"w1": {"x": 2}}}
    assert admin_client.get("/api/store/radar").json() == {
        f"data/users/{low}/agent/track": {"w1": {"x": 1}},
        "data/users/axb@test.no/agent/track": {"w1": {"near": "aXb@test.no"}},
        "data/users/axbc@test.no/agent/track": {"w1": {"near": "aXbc@test.no"}}}
    guests = [r["owner"] for r in rows(hub) if r["collection"].endswith("/guests/main")]
    assert guests == ["axb@test.no", "axbc@test.no"]  # the odd owner's reply is gone, the others' are not


# ---------------------------------------------------------------- final review: public off keeps hidden replies hidden
def test_hidden_replies_stay_hidden_after_public_goes_off(hub, user_client, client):
    from tests.test_guest_api import SECRET, gget, gput
    from tests.test_share_links import share, token_of

    recipe = ("async function hubCard({db, user}) { const z = `data/users/${user}/guests/jul`;"
              " const [c, d] = await Promise.all([db.collection(z).get(), db.doc(`${z}/abc`).get()]);"
              " return c.size + '|' + d.exists; }")
    hub.save_page("radar", f"<!doctype html><html><body><script data-hub-card>{recipe}</script></body></html>",
                  create=True, private=False)
    path = hub._meta_path("radar")
    hub._write_meta(path, {**hub._read_meta(path), "data": "shared"})
    hub.set_public("radar", public=True, guests_hidden=True)
    tok = token_of(share(user_client, title="Jul"))
    assert gput(client, tok, "guests/abc", {"t": "secret wish"}).status_code == 200
    assert gput(client, tok, "guests/abc/notes/n1", {"t": "more"}).status_code == 200
    col = f"data/users/{U}/guests/jul"
    hub.set_public("radar", public=False, via_connector=True)  # as update_app_info(public_sharing=false) does
    for doc in (f"{col}/abc", f"{col}/abc/notes/n1"):
        assert get(user_client, "radar", doc) is None
        assert hub.doc_get("radar", U, doc) is None
    for c in (col, f"{col}/abc/notes"):
        assert ids(user_client, "radar", c) == []
        assert hub.doc_list("radar", U, c) == {}
    assert user_client.get("/api/store/radar").json() == {}
    assert hub.doc_overview("radar", U) == {}
    assert hub.card_result(U, "radar", "Europe/Oslo").text == "0|false"
    # the owner still cannot write there, nor turn off what keeps the zone a zone
    for merge in ("false", "true"):
        assert put(user_client, "radar", f"{col}/abc", {"t": "mine now"}, merge=merge).status_code == 403
        with pytest.raises(hub.ReadOnly):
            hub.doc_set("radar", U, f"{col}/abc", {"t": "mine now"}, merge=merge == "true")
    with pytest.raises(hub.HubError):
        hub.set_data_mode("radar", False)
    with pytest.raises(hub.HubError):
        hub.set_public("radar", guests_hidden=False, via_connector=True)
    assert hub._read_meta(path)["data"] == "shared" and hub._read_meta(path)["guests_hidden"] is True
    # public on again: the guest finds the reply as they left it
    hub.set_public("radar", public=True)
    got = gget(client, tok, "guests/abc", secret=SECRET).json()["data"]
    assert got["t"] == "secret wish" and got["_mine"] is True
    assert gget(client, tok, "guests/abc/notes/n1", secret=SECRET).json()["data"]["t"] == "more"
