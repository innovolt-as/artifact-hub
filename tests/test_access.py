"""Who sees an app: everyone, specific people or only admin (app/access.py), enforced everywhere."""
import json

import pytest

from app import access

FRIEND = "venn@test.no"


@pytest.mark.parametrize("meta,lvl", [({}, "all"), ({"admin_only": True}, "admin"),
    ({"access": "people", "people": ["a@x.no"]}, "people"),
    ({"admin_only": True, "access": "people", "people": ["a@x.no"]}, "admin")])
def test_level(meta, lvl):
    assert access.level(meta) == lvl


def test_can_see_rules():
    m = {"access": "people", "people": [" Venn@Test.no "]}
    assert access.can_see(m, "venn@test.no", False) and access.can_see(m, "VENN@test.no", False)
    assert not access.can_see(m, "user@test.no", False) and access.can_see(m, "admin@test.no", True)
    assert not access.can_see({"admin_only": True}, FRIEND, False) and access.can_see({}, "hvem@som.helst", False)


def test_set_level_keeps_list():
    m = {}
    access.set_level(m, "people", ["B@x.no", "a@x.no ", "b@x.no"])
    assert m == {"access": "people", "people": ["b@x.no", "a@x.no"]}
    access.set_level(m, "all")
    assert access.level(m) == "all" and m["people"] == ["b@x.no", "a@x.no"]
    access.set_level(m, "admin")
    assert m["admin_only"] is True and "access" not in m
    access.set_level(m, "people")
    assert access.level(m) == "people" and access.people(m) == ["b@x.no", "a@x.no"]
    with pytest.raises(ValueError):
        access.set_level(m, "noen")


def test_labels():
    assert (access.label({}), access.describe({})) == ("🌍 Alle", "alle")
    assert (access.label({"admin_only": True}), access.describe({"admin_only": True})) == ("🔒 Bare meg", "bare meg")
    assert access.label({"access": "people", "people": ["a@x.no"]}) == "👥 1 person"
    assert access.describe({"access": "people", "people": ["a@x.no", "b@x.no"]}) == "2 personer"


def test_people_app_everywhere(hub, make_page, admin_client, user_client, friend_client):
    make_page("p", "people", [FRIEND])
    hub.ICONS_DIR.mkdir(exist_ok=True)
    (hub.ICONS_DIR / "p.png").write_bytes(b"\x89PNG")
    (hub.ARTIFACTS_DIR / "k.link.json").write_text(
        json.dumps({"title": "K", "url": "https://x.no/", "access": "people", "people": [FRIEND]}))
    for c, ok in ((friend_client, True), (admin_client, True), (user_client, False)):
        assert (c.get("/a/p/").status_code == 200) is ok
        assert (c.get("/icon/p").status_code == 200) is ok
        assert (c.get("/go/k").status_code == 302) is ok
        assert (c.get("/api/store/p/c", params={"path": "x"}).status_code == 200) is ok
    assert hub.list_artifacts("user@test.no") == []
    with pytest.raises(hub.HubError):
        hub.doc_scope("p", "user@test.no", "x")
    assert hub.doc_scope("p", FRIEND, "x") == (FRIEND, "x")


def test_admin_only_hidden_from_people_on_its_list(hub, make_page, friend_client):
    make_page("p", "people", [FRIEND])
    meta = hub._read_meta(hub._meta_path("p"))
    access.set_level(meta, "admin")
    hub._write_meta(hub._meta_path("p"), meta)
    assert friend_client.get("/a/p/").status_code == 404 and hub.list_artifacts(FRIEND) == []


def test_people_list_only_shown_to_admin(hub, make_page):
    make_page("p", "people", [FRIEND])
    assert hub.list_artifacts(FRIEND)[0]["people"] == []
    a = hub.list_artifacts("admin@test.no")[0]
    assert a["people"] == [FRIEND] and a["access"] == "people" and a["access_label"] == "👥 1 person"


def test_access_survives_reupload(hub, make_page, admin_client, upload):
    make_page("p", "people", [FRIEND])
    upload(admin_client, "p.html", "<body>ny</body>")
    meta = hub._read_meta(hub._meta_path("p"))
    assert access.level(meta) == "people" and access.people(meta) == [FRIEND]


def test_private_flag_maps_to_levels_and_keeps_list(hub, make_page):
    make_page("p", "people", [FRIEND])
    hub.set_info("p", private=True)
    meta = hub._read_meta(hub._meta_path("p"))
    assert access.level(meta) == "admin" and access.people(meta) == [FRIEND]
    hub.save_page("p", "<body>x</body>", create=False, private=False)
    meta = hub._read_meta(hub._meta_path("p"))
    assert access.level(meta) == "all" and access.people(meta) == [FRIEND]
