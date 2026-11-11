"""Per-app settings for public sharing: "public", "public_read", "guests_hidden" and "agent" in a shared app's meta."""
import json

import pytest

from app import public
from tests.test_append import make_append
from tests.test_shared_data import make_shared


def test_zone_of():
    z = public.zone_of("data/users/A@T.no/public/jul")
    assert z == public.Zone("a@t.no", "public", "jul")
    assert public.zone_of("data/users/a@t.no/guests/jul/x/sub") == public.Zone("a@t.no", "guests", "jul")
    assert public.zone_of("data/users/a@t.no/agent/track") == public.Zone("a@t.no", "agent", None)
    assert public.zone_of("data/users/a@t.no/agent") == public.Zone("a@t.no", "agent", None)
    for c in ("data/users/a@t.no/public", "data/users/a@t.no", "public/jul", "data/users/a@t.no/wishes",
              "data/users/a@t.no/public/bad name"):
        assert public.zone_of(c) is None


def test_zone_collection():
    assert public.zone_collection("A@T.no", "public", "jul") == "data/users/a@t.no/public/jul"
    assert public.zone_collection("a@t.no", "guests", "jul", "x") == "data/users/a@t.no/guests/jul/x"
    assert public.zone_collection("a@t.no", "agent", None) == "data/users/a@t.no/agent"


def meta_of(hub, slug):
    return hub._read_meta(hub._meta_path(slug))


def add_guest_docs(hub, slug, email="a@t.no", name="jul", n=1):
    with hub.db() as con:
        for i in range(n):
            con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                        (slug, email, public.zone_collection(email, "guests", name), f"r{i}", json.dumps({"i": i})))


def count_docs(hub, slug):
    with hub.db() as con:
        return con.execute("SELECT COUNT(*) FROM docs WHERE slug=?", (slug,)).fetchone()[0]


def test_settings_need_shared_data(hub, make_page):
    make_page("radar")
    for kw in ({"public": True}, {"agent": True}, {"guests_hidden": True}, {"public_read": ["products"]}):
        with pytest.raises(hub.HubError):
            hub.set_public("radar", **kw)
    assert hub.set_public("radar", public=False)["public"] is False


def test_settings_stored_and_listed(hub, make_page):
    make_shared(hub, make_page, "radar")
    got = hub.set_public("radar", public=True, public_read=["products", "tags"], guests_hidden=True, agent=True)
    assert got == {"public": True, "public_read": ["products", "tags"], "guests_hidden": True, "agent": True}
    meta = meta_of(hub, "radar")
    assert meta["public"] is True and meta["public_read"] == ["products", "tags"]
    assert meta["guests_hidden"] is True and meta["agent"] is True
    item = next(a for a in hub.list_artifacts("a@t.no") if a["slug"] == "radar")
    assert (item["public"], item["public_read"], item["guests_hidden"], item["agent"]) == (True, ["products", "tags"], True, True)
    got = hub.set_public("radar", public=False, public_read=[], agent=False)
    assert got == {"public": False, "public_read": [], "guests_hidden": True, "agent": False}
    assert "public" not in meta_of(hub, "radar") and "public_read" not in meta_of(hub, "radar")


def test_settings_survive_reupload(hub, make_page):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True, public_read=["products"], guests_hidden=True, agent=True)
    hub.save_page("radar", "<!doctype html><html><body>v2</body></html>", create=False, private=False)
    meta = meta_of(hub, "radar")
    assert meta["public"] is True and meta["public_read"] == ["products"]
    assert meta["guests_hidden"] is True and meta["agent"] is True


def test_public_read_rules(hub, make_page):
    make_shared(hub, make_page, "radar")
    for bad in (["bad name"], ["data"], [f"c{i}" for i in range(11)]):
        with pytest.raises(hub.HubError):
            hub.set_public("radar", public_read=bad)
    assert hub.set_public("radar", public_read=["a", "a", "b"])["public_read"] == ["a", "b"]
    assert hub.set_public("radar", public_read=[f"c{i}" for i in range(10)])["public_read"][-1] == "c9"


def test_append_and_public_read_cannot_overlap(hub, make_page):
    make_append(hub, make_page, "radar", ("queue",))
    with pytest.raises(hub.HubError):
        hub.set_public("radar", public_read=["queue"])
    assert hub.set_public("radar", public_read=["products"])["public_read"] == ["products"]
    with pytest.raises(hub.HubError):
        hub.set_append("radar", ["queue", "products"])
    assert hub.set_append("radar", ["queue"]) == ["queue"]


def test_shared_data_cannot_go_off_while_public_or_agent(hub, make_page):
    make_shared(hub, make_page, "radar")
    for kw, off in (({"public": True}, {"public": False}), ({"agent": True}, {"agent": False})):
        hub.set_public("radar", **kw)
        with pytest.raises(hub.HubError):
            hub.set_data_mode("radar", False)
        hub.set_public("radar", **off)
        hub.set_data_mode("radar", True)
    hub.set_data_mode("radar", False)
    assert "data" not in meta_of(hub, "radar")


def test_guests_hidden_off_refused_via_connector_with_replies(hub, make_page):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", guests_hidden=True)
    add_guest_docs(hub, "radar")
    with pytest.raises(hub.HubError):
        hub.set_public("radar", guests_hidden=False, via_connector=True)
    assert meta_of(hub, "radar")["guests_hidden"] is True and count_docs(hub, "radar") == 1
    hub.set_public("radar", guests_hidden=True, via_connector=True)  # on is always allowed
    make_shared(hub, make_page, "empty")
    hub.set_public("empty", guests_hidden=True)
    assert hub.set_public("empty", guests_hidden=False, via_connector=True)["guests_hidden"] is False


def test_guests_hidden_off_on_admin_page_wipes(hub, make_page):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", guests_hidden=True)
    add_guest_docs(hub, "radar", "a@t.no", "jul", 2)
    add_guest_docs(hub, "radar", "b@t.no", "x", 1)
    with hub.db() as con:  # not a guests zone, must stay
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                    ("radar", "a@t.no", "data/users/a@t.no/public/jul", "keep", "{}"))
    assert hub.guest_doc_count("radar") == 3
    with pytest.raises(hub.HubError):
        hub.set_public("radar", guests_hidden=False)
    assert count_docs(hub, "radar") == 4
    assert hub.set_public("radar", guests_hidden=False, wipe_guests=True)["guests_hidden"] is False
    assert hub.guest_doc_count("radar") == 0 and count_docs(hub, "radar") == 1
    assert "guests_hidden" not in meta_of(hub, "radar")


def test_zone_name_clash(hub, make_page):
    make_shared(hub, make_page, "radar")
    assert hub.zone_name_clash("radar") == 0
    add_guest_docs(hub, "radar", n=2)
    with hub.db() as con:
        for col in ("data/users/a@t.no/agent/x", "data/users/a@t.no/wishes", "data/users/a@t.no/public"):
            con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                        ("radar", "a@t.no", col, "d", "{}"))
    assert hub.zone_name_clash("radar") == 4


def test_defaults_unchanged(hub, make_page):
    make_page("plain")
    item = next(a for a in hub.list_artifacts("a@t.no") if a["slug"] == "plain")
    assert (item["public"], item["public_read"], item["guests_hidden"], item["agent"]) == (False, [], False, False)
    assert public.is_public({"public": True}) is False and public.public_read({"public_read": ["x"]}) == []


def test_public_settings_routes(hub, make_page, admin_client, user_client):
    make_shared(hub, make_page, "radar")
    body = {"slug": "radar", "public": True, "public_read": ["products"]}
    assert user_client.post("/api/public-settings", json=body).status_code in (401, 403)
    r = admin_client.post("/api/public-settings", json=body)
    assert r.status_code == 200 and r.json() == {"ok": True, "public": True, "public_read": ["products"],
                                                 "guests_hidden": False, "agent": False}
    assert admin_client.post("/api/public-settings", json={"slug": "radar", "public_read": ["data"]}).status_code == 400
    assert admin_client.post("/api/public-settings", json={"slug": "nope", "public": True}).status_code == 404
    add_guest_docs(hub, "radar")
    r = admin_client.get("/api/public-settings", params={"slug": "radar"}).json()
    assert r["public"] is True and r["guest_docs"] == 1 and r["clash"] == 1 and r["links"] == 0
    admin_client.post("/api/public-settings", json={"slug": "radar", "guests_hidden": True})
    assert admin_client.post("/api/public-settings", json={"slug": "radar", "guests_hidden": False}).status_code == 400
    r = admin_client.post("/api/public-settings", json={"slug": "radar", "guests_hidden": False, "wipe_guests": True})
    assert r.status_code == 200 and r.json()["guests_hidden"] is False
