"""Secret links per user and share name (app/public.py, /api/share): one per (app, owner, name)."""
import pytest

from app import access, public
from tests.test_public_settings import add_guest_docs, count_docs
from tests.test_shared_data import make_shared

U = "user@test.no"


def share(c, slug="radar", **body):
    return c.post(f"/api/share/{slug}", json={"name": "jul", "action": "create", **body})


def token_of(r):
    url = r.json()["link"]["url"]
    assert url.startswith("https://hub.test/p/") and url.endswith("/")
    return url.split("/")[-2]


@pytest.fixture
def pub(hub, make_page):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)


def test_create_is_idempotent_and_per_name(pub, user_client):
    a, b = share(user_client, title="Jul"), share(user_client, title="Julen")
    assert a.json()["link"]["url"] == b.json()["link"]["url"]
    assert b.json()["link"]["title"] == "Julen"
    assert share(user_client, name="bursdag").json()["link"]["url"] != a.json()["link"]["url"]
    got = user_client.get("/api/share/radar", params={"name": "jul"}).json()
    assert got == {"link": b.json()["link"], "guest_docs": 0, "locked": False}


def test_rotate_kills_old_token(hub, pub, user_client):
    old = token_of(share(user_client))
    new = token_of(share(user_client, action="rotate"))
    assert new != old
    assert hub.resolve_link(old) is None
    link, meta = hub.resolve_link(new)
    assert (link.slug, link.owner, link.name) == ("radar", U, "jul")
    assert meta["public"] is True


def test_off_keeps_documents(hub, pub, user_client):
    tok = token_of(share(user_client))
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,?,?,0)",
                    ("radar", U, public.zone_collection(U, "public", "jul"), "d", "{}"))
    add_guest_docs(hub, "radar", U, "jul", 2)
    r = share(user_client, action="off")
    assert r.status_code == 200 and r.json()["link"] is None and r.json()["guest_docs"] == 2
    assert hub.resolve_link(tok) is None
    assert count_docs(hub, "radar") == 3


def test_clear_only_this_name(hub, pub, user_client):
    share(user_client)
    add_guest_docs(hub, "radar", U, "jul", 2)
    add_guest_docs(hub, "radar", U, "bursdag", 1)
    r = share(user_client, action="clear")
    assert r.json()["guest_docs"] == 0 and r.json()["link"] is not None
    assert count_docs(hub, "radar") == 1
    assert user_client.get("/api/share/radar", params={"name": "bursdag"}).json()["guest_docs"] == 1


def test_share_needs_public_switch_and_access(hub, make_page, pub, user_client):
    make_shared(hub, make_page, "plain")
    assert share(user_client, "plain").status_code == 404
    assert user_client.get("/api/share/plain", params={"name": "jul"}).status_code == 404
    make_shared(hub, make_page, "hidden", level="admin")
    hub.set_public("hidden", public=True)
    assert share(user_client, "hidden").status_code == 404
    assert share(user_client, "nope").status_code == 404
    from tests.conftest import make_client
    assert share(make_client()).status_code == 401


def test_bad_name_refused(pub, user_client):
    for name in ("a b", "", "x" * 65, 5, None):
        assert share(user_client, name=name).status_code == 400
    assert share(user_client, action="burn").status_code == 400
    assert user_client.get("/api/share/radar", params={"name": "a b"}).status_code == 400
    assert user_client.post("/api/share/radar", content="x").status_code == 415


def test_link_dead_while_public_off_alive_again(hub, pub, user_client):
    tok = token_of(share(user_client))
    hub.set_public("radar", public=False)
    assert hub.resolve_link(tok) is None
    hub.set_public("radar", public=True)
    assert hub.resolve_link(tok) is not None


def test_link_dead_when_owner_loses_access_or_is_removed(hub, make_page, pub, user_client):
    tok = token_of(share(user_client))
    path = hub._meta_path("radar")
    meta = hub._read_meta(path)
    access.set_level(meta, "admin")
    hub._write_meta(path, meta)
    assert hub.resolve_link(tok) is None
    access.set_level(meta, "all")
    hub._write_meta(path, meta)
    assert hub.resolve_link(tok) is not None
    # a person from the people list, who is then removed
    from tests.conftest import make_client
    make_shared(hub, make_page, "club", level="people")
    path = hub._meta_path("club")
    meta = hub._read_meta(path)
    access.set_level(meta, "people", ["venn@test.no"])
    hub._write_meta(path, meta)
    hub.set_public("club", public=True)
    with hub.db() as con:
        access.invite(con, "venn@test.no")
    friend = make_client("venn@test.no")
    ftok = token_of(share(friend, "club"))
    assert hub.resolve_link(ftok) is not None
    hub.remove_person("venn@test.no")
    assert hub.resolve_link(ftok) is None


def test_rename_app_moves_links(hub, pub, user_client, admin_client):
    tok = token_of(share(user_client))
    assert admin_client.post("/api/edit", data={"slug": "radar", "new_slug": "radar2"}).status_code == 200
    link, _ = hub.resolve_link(tok)
    assert link.slug == "radar2"


def test_delete_my_data_removes_links_zones_and_guest_docs(hub, pub, user_client):
    share(user_client)
    share(user_client, name="bursdag")
    add_guest_docs(hub, "radar", U, "jul", 2)
    assert user_client.post("/api/me/delete-data", json={"confirm": "SLETT"}).status_code == 200
    with hub.db() as con:
        assert public.links_of(con, U) == []
    assert count_docs(hub, "radar") == 0


def test_remove_person_removes_links_only(hub, pub, user_client):
    share(user_client)
    add_guest_docs(hub, "radar", U, "jul", 2)
    with hub.db() as con:
        access.invite(con, U)
    hub.remove_person(U)
    with hub.db() as con:
        assert public.links_of(con, U) == []
    assert count_docs(hub, "radar") == 2


def test_guest_doc_count_never_shows_content(hub, pub, user_client):
    share(user_client)
    add_guest_docs(hub, "radar", U, "jul", 3)
    r = user_client.get("/api/share/radar", params={"name": "jul"})
    assert r.json()["guest_docs"] == 3 and '"i"' not in r.text and "r0" not in r.text


def test_share_list_and_settings_count(hub, pub, user_client, admin_client):
    share(user_client, title="Jul")
    add_guest_docs(hub, "radar", U, "jul", 2)
    items = user_client.get("/api/share").json()["links"]
    assert len(items) == 1
    assert {k: items[0][k] for k in ("slug", "name", "title", "guest_docs")} == \
        {"slug": "radar", "name": "jul", "title": "Jul", "guest_docs": 2}
    assert items[0]["app_title"] and items[0]["url"].startswith("https://hub.test/p/")
    assert admin_client.get("/api/public-settings", params={"slug": "radar"}).json()["links"] == 1


def test_locked_flag(hub, pub, user_client):
    from tests.conftest import lock
    lock(U, "radar")
    assert share(user_client).json()["locked"] is True
