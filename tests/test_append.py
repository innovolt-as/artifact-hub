"""Add-only collections: "append": [names] in a shared app's meta lets everyone who sees the app add documents there."""
import time

import pytest

from app import shared
from tests.test_shared_data import get, make_shared, put


def make_append(hub, make_page, slug="fylgje", names=("queue",)):
    make_shared(hub, make_page, slug)
    path = hub._meta_path(slug)
    meta = hub._read_meta(path)
    meta["append"] = list(names)
    hub._write_meta(path, meta)


def test_appendable_rules():
    meta = {"data": "shared", "append": ["queue"]}
    assert shared.appendable(meta, "queue") is True
    assert shared.appendable(meta, "queue/x/items") is False
    assert shared.appendable(meta, "briefs") is False
    assert shared.appendable({"data": "shared", "append": ["data/users/a@t.no"]}, "data/users/a@t.no") is False
    assert shared.appendable({"append": ["queue"]}, "queue") is False
    assert shared.appendable({"data": "shared", "append": ["data"]}, "data") is False
    assert shared.appendable({"data": "shared", "append": "queue"}, "queue") is False


def test_user_can_add_to_queue(hub, make_page, admin_client, user_client):
    make_append(hub, make_page)
    assert put(user_client, "fylgje", "queue/q1", {"question": "sushi", "_added_by": "evil@x.no"}).status_code == 200
    doc = get(admin_client, "fylgje", "queue/q1")
    assert doc["question"] == "sushi"
    assert doc["_added_by"] == "user@test.no"
    assert isinstance(doc["_added_at"], int) and abs(doc["_added_at"] - time.time()) < 5


def test_add_only_refuses_overwrite_merge_delete(hub, make_page, admin_client, user_client):
    make_append(hub, make_page)
    put(user_client, "fylgje", "queue/q1", {"question": "sushi"})
    assert put(user_client, "fylgje", "queue/q1", {"question": "pizza"}).status_code == 403
    assert put(user_client, "fylgje", "queue/q1", {"question": "pizza"}, merge="true").status_code == 403
    assert put(user_client, "fylgje", "queue/q9", {"question": "pizza"}, merge="true").status_code in (403, 404)
    assert user_client.delete("/api/store/fylgje/d", params={"path": "queue/q1"}).status_code == 403
    assert get(admin_client, "fylgje", "queue/q1")["question"] == "sushi"
    assert put(admin_client, "fylgje", "queue/q1", {"status": "ferdig"}, merge="true").status_code == 200
    doc = get(admin_client, "fylgje", "queue/q1")
    assert doc["status"] == "ferdig" and doc["question"] == "sushi" and doc["_added_by"] == "user@test.no"


def test_stamp_cannot_be_forged_or_lost(hub, make_page, admin_client, user_client):
    make_append(hub, make_page)
    put(user_client, "fylgje", "queue/q1", {"question": "sushi"})
    added_at = get(admin_client, "fylgje", "queue/q1")["_added_at"]
    assert put(admin_client, "fylgje", "queue/q1", {"question": "x"}).status_code == 200
    doc = get(admin_client, "fylgje", "queue/q1")
    assert doc["question"] == "x" and doc["_added_by"] == "user@test.no" and doc["_added_at"] == added_at
    assert put(admin_client, "fylgje", "queue/q2", {"_added_by": "z@x.no"}).status_code == 200
    assert get(admin_client, "fylgje", "queue/q2")["_added_by"] == "admin@test.no"


def test_stamp_keeps_old_fields():
    assert shared.stamp({"a": 1}, None, "A@T.no", 7) == {"a": 1, "_added_by": "a@t.no", "_added_at": 7}
    old = {"_added_by": "u@t.no", "_added_at": 3}
    assert shared.stamp({"a": 2, "_added_by": "z@x.no"}, old, "admin@t.no", 9) == {
        "a": 2, "_added_by": "u@t.no", "_added_at": 3}


def test_other_shared_collections_stay_admin_only(hub, make_page, user_client):
    make_append(hub, make_page)
    assert put(user_client, "fylgje", "entries/kaffe", {"n": 1}).status_code == 403
    assert put(user_client, "fylgje", "queue/q1/items/i1", {"n": 1}).status_code == 403


def test_branch_is_never_add_only(hub, make_page, user_client):
    make_append(hub, make_page, names=("queue", "data/users/user@test.no"))
    assert put(user_client, "fylgje", "data/users/user@test.no/p", {"x": 1}).status_code == 200
    assert put(user_client, "fylgje", "data/users/user@test.no/p", {"x": 2}).status_code == 200
    assert get(user_client, "fylgje", "data/users/user@test.no/p") == {"x": 2}


def test_append_survives_reupload(hub, admin_client, upload):
    upload(admin_client, "fylgje.html", "<!doctype html><html><body>1</body></html>")
    path = hub._meta_path("fylgje")
    hub._write_meta(path, {**hub._read_meta(path), "data": "shared", "append": ["queue"]})
    upload(admin_client, "fylgje.html", "<!doctype html><html><body>2</body></html>")
    assert hub._read_meta(path)["append"] == ["queue"]


def test_connector_rules_match(hub, make_page, admin_client):
    make_append(hub, make_page)
    stored = hub.doc_set("fylgje", "user@test.no", "queue/q3", {"question": "tog", "_added_by": "evil@x.no"})
    assert stored["_added_by"] == "user@test.no"
    with pytest.raises(hub.ReadOnly):
        hub.doc_set("fylgje", "user@test.no", "queue/q3", {"question": "fly"})
    with pytest.raises(hub.ReadOnly):
        hub.doc_set("fylgje", "user@test.no", "queue/q3", {"question": "fly"}, merge=True)
    with pytest.raises(hub.ReadOnly):
        hub.doc_delete("fylgje", "user@test.no", "queue/q3")
    with pytest.raises(hub.ReadOnly):
        hub.doc_set("fylgje", "user@test.no", "entries/kaffe", {"n": 1})
    assert get(admin_client, "fylgje", "queue/q3")["question"] == "tog"
    assert hub.doc_delete("fylgje", "admin@test.no", "queue/q3") is True
