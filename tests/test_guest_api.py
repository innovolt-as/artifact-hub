"""The guest API (/api/public/<token>/...): the only routes that answer people who are not logged in.
A guest reaches the link owner's public/<name> (read), guests/<name> (read, create, delete own) and single documents
of the shared collections in public_read, and nothing else."""
import json

import pytest

from app import access, public
from tests.conftest import make_client
from tests.test_share_links import U, share, token_of
from tests.test_shared_data import make_shared, put

SECRET = "a" * 32
OTHER = "b" * 32
BRANCH = f"data/users/{U}"


@pytest.fixture
def tok(hub, make_page, user_client, admin_client):
    """A link to user@test.no's "jul" in radar, with a public doc, a private wish, another share name and a product."""
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True, public_read=["products"])
    t = token_of(share(user_client, title="Jul"))
    share(user_client, name="bursdag")
    assert put(user_client, "radar", f"{BRANCH}/public/jul/abc", {"title": "Sykkel"}).status_code == 200
    assert put(user_client, "radar", f"{BRANCH}/public/jul/abc/notes/n1", {"text": "rød"}).status_code == 200
    assert put(user_client, "radar", f"{BRANCH}/public/bursdag/abc", {"title": "Hemmelig"}).status_code == 200
    assert put(user_client, "radar", f"{BRANCH}/private/wishes/x", {"title": "Privat"}).status_code == 200
    assert put(admin_client, "radar", "products/k1", {"name": "Kaffe"}).status_code == 200
    assert put(admin_client, "radar", "other/x", {"name": "Annet"}).status_code == 200
    return t


def gget(c, tok, path, route="d", secret=None):
    return c.get(f"/api/public/{tok}/{route}", params={"path": path},
                 headers={"X-Hub-Guest": secret} if secret else {})


def gput(c, tok, path, data, secret=SECRET, **params):
    headers = {"X-Hub-Guest": secret} if secret else {}
    body = data if isinstance(data, (bytes, str)) else json.dumps(data)
    return c.put(f"/api/public/{tok}/d", params={"path": path, **params}, content=body,
                 headers={"content-type": "application/json", **headers})


def gdel(c, tok, path, secret=SECRET):
    return c.delete(f"/api/public/{tok}/d", params={"path": path}, headers={"X-Hub-Guest": secret} if secret else {})


def stored(hub, collection, doc_id):
    with hub.db() as con:
        row = con.execute("SELECT owner, data FROM docs WHERE slug='radar' AND collection=? AND doc_id=?",
                          (collection, doc_id)).fetchone()
    return (row["owner"], json.loads(row["data"])) if row else None


def guests_col(rest=""):
    return public.zone_collection(U, "guests", "jul", rest)


def test_guest_reads_public_zone_of_this_name_only(client, tok):
    assert gget(client, tok, "public/abc").json() == {"data": {"title": "Sykkel"}}
    assert gget(client, tok, "public/abc/notes/n1").json() == {"data": {"text": "rød"}}
    assert client.get(f"/api/public/{tok}/c", params={"path": "public"}).json() == {
        "docs": [{"id": "abc", "data": {"title": "Sykkel"}}]}
    assert client.get(f"/api/public/{tok}/c", params={"path": "public/abc/notes"}).json()["docs"][0]["id"] == "n1"
    assert gget(client, tok, "public/nope").json() == {"data": None}
    # the owner's other share name, private data and anything spelled as a stored path are out of reach
    for path in ("public/bursdag/abc", "bursdag/abc", "wishes/x", f"{BRANCH}/private/wishes/x", f"{BRANCH}/public/bursdag/abc",
                 "data/users/user@test.no/public/jul/abc"):
        r = gget(client, tok, path)
        assert r.status_code in (400, 404) or r.json() == {"data": None}, path
        assert "Hemmelig" not in r.text and "Privat" not in r.text
    for path in ("wishes", "bursdag", "data", "products", f"{BRANCH}/public/bursdag"):
        r = client.get(f"/api/public/{tok}/c", params={"path": path})
        assert r.status_code in (400, 404) and "Hemmelig" not in r.text and "Privat" not in r.text, path


def test_guest_cannot_write_public(hub, client, tok):
    before = stored(hub, public.zone_collection(U, "public", "jul"), "abc")
    for path in ("public/abc", "public/new", "public/abc/notes/n2"):
        r = gput(client, tok, path, {"title": "Hacked"})
        assert r.status_code in (403, 404), path
        assert gdel(client, tok, path).status_code in (403, 404), path
    assert stored(hub, public.zone_collection(U, "public", "jul"), "abc") == before
    assert stored(hub, public.zone_collection(U, "public", "jul"), "new") is None
    assert stored(hub, public.zone_collection(U, "public", "jul", "abc/notes"), "n1") is not None
    for path in ("wishes/x", "products/k1", "agent/x"):
        assert gput(client, tok, path, {"t": 1}).status_code in (403, 404), path
    assert stored(hub, f"{BRANCH}/private/wishes", "x")[1] == {"title": "Privat"}


def test_guest_creates_and_second_guest_is_refused(hub, client, tok):
    r = gput(client, tok, "guests/abc", {"taken": True, "by": "Kari"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    owner, data = stored(hub, guests_col(), "abc")
    assert owner == U and data["by"] == "Kari"
    assert data["_guest"] == public.guest_hash(SECRET) and isinstance(data["_added_at"], int)
    r = gput(make_client(), tok, "guests/abc", {"taken": True, "by": "Ola"}, secret=OTHER)
    assert r.status_code == 403 and U not in r.text
    assert stored(hub, guests_col(), "abc")[1]["by"] == "Kari"
    # a sub-collection under a guest document works the same way
    assert gput(client, tok, "guests/abc/replies/r1", {"t": "hei"}).status_code == 200
    assert stored(hub, guests_col("abc/replies"), "r1")[0] == U


def test_guest_sees_mine_flag_not_hash(client, tok):
    gput(client, tok, "guests/abc", {"t": 1})
    gput(client, tok, "guests/def", {"t": 2}, secret=OTHER)
    mine = gget(client, tok, "guests/abc", secret=SECRET).json()["data"]
    assert mine == {"t": 1, "_added_at": mine["_added_at"], "_mine": True}
    assert gget(client, tok, "guests/abc", secret=OTHER).json()["data"]["_mine"] is False
    assert gget(client, tok, "guests/abc").json()["data"]["_mine"] is False
    listed = client.get(f"/api/public/{tok}/c", params={"path": "guests"}, headers={"X-Hub-Guest": SECRET})
    assert [(d["id"], d["data"]["_mine"]) for d in listed.json()["docs"]] == [("abc", True), ("def", False)]
    h = public.guest_hash(SECRET)
    for r in (listed, gget(client, tok, "guests/abc", secret=SECRET), gget(client, tok, "guests/def")):
        assert "_guest" not in r.text and h not in r.text and SECRET not in r.text


def test_guest_input_cannot_fake_hub_fields(hub, client, tok):
    gput(client, tok, "guests/abc", {"t": 1, "_guest": public.guest_hash(OTHER), "_added_at": 1, "_mine": True,
                                     "_added_by": "admin@test.no"})
    data = stored(hub, guests_col(), "abc")[1]
    assert data["_guest"] == public.guest_hash(SECRET) and data["_added_at"] > 1
    assert "_mine" not in data and "_added_by" not in data


def test_guest_deletes_only_own(hub, client, tok):
    gput(client, tok, "guests/abc", {"t": 1})
    r = gdel(make_client(), tok, "guests/abc", secret=OTHER)
    assert r.status_code == 403 and U not in r.text
    assert stored(hub, guests_col(), "abc") is not None
    assert gdel(client, tok, "guests/abc").status_code == 200
    assert stored(hub, guests_col(), "abc") is None
    assert gdel(client, tok, "guests/abc").status_code == 404
    # a document in a guests collection without a hub-made _guest (from before the switch) belongs to no guest
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('radar',?,?,?,?,0)",
                    (U, guests_col(), "old", json.dumps({"_guest": "ø" * 64})))
    assert gdel(client, tok, "guests/old").status_code == 403
    assert gget(client, tok, "guests/old", secret=SECRET).json()["data"] == {"_mine": False}


def test_no_merge_no_overwrite(hub, client, tok):
    gput(client, tok, "guests/abc", {"t": 1, "keep": True})
    assert gput(client, tok, "guests/abc", {"t": 2}).status_code == 403
    assert gput(client, tok, "guests/abc", {"t": 3}, merge="true").status_code == 403
    data = stored(hub, guests_col(), "abc")[1]
    assert data["t"] == 1 and data["keep"] is True
    assert gput(client, tok, "guests/new", {"t": 3}, merge="true").status_code == 200  # there is no merge: a create
    assert stored(hub, guests_col(), "new")[1]["t"] == 3


def test_guest_doc_size_and_quota(hub, client, tok):
    exact = json.dumps({"t": "x" * (4096 - len(json.dumps({"t": ""})))})
    assert len(exact) == hub.MAX_GUEST_DOC_BYTES
    assert gput(client, tok, "guests/fits", exact).status_code == 200
    over = json.dumps({"t": "x" * (4097 - len(json.dumps({"t": ""})))})
    r = gput(client, tok, "guests/big", over)
    assert r.status_code == 413
    assert stored(hub, guests_col(), "big") is None
    assert gput(client, tok, "guests/huge", "{" + " " * 1_000_000 + "}").status_code == 413
    # the quota: MAX_GUEST_DOCS per link, sub-collections included; other names do not count
    with hub.db() as con:
        for i in range(hub.MAX_GUEST_DOCS - 2):
            con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('radar',?,?,?,?,0)",
                        (U, guests_col("fits/sub"), f"q{i}", "{}"))
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('radar',?,?,?,?,0)",
                    (U, public.zone_collection(U, "guests", "bursdag"), "elsewhere", "{}"))
    public._guest_writes.clear()
    assert gput(client, tok, "guests/last", {"t": 1}).status_code == 200  # the 500th
    r = gput(client, tok, "guests/one-too-many", {"t": 1})
    assert r.status_code == 429
    assert stored(hub, guests_col(), "one-too-many") is None


def test_bad_bodies(client, tok):
    assert gput(client, tok, "guests/a", "not json").status_code == 400
    assert gput(client, tok, "guests/a", "[1, 2]").status_code == 400
    assert gput(client, tok, "guests/a", "").status_code == 400
    assert gput(client, tok, "guests/a", b"\xff\xfe{}").status_code == 400
    # values that would be stored but break every later read of the zone
    for raw in ('{"t": NaN}', '{"t": Infinity}', '{"t": -Infinity}', '{"t": 1e999}'):
        assert gput(client, tok, "guests/a", raw).status_code == 400, raw
    assert gput(client, tok, "guests/a", '{"t": 1.5e300}').status_code == 200
    for n in (2040, 40):
        assert gput(client, tok, "guests/deep", '{"t": ' + "[" * n + "]" * n + "}").status_code == 400, n
    assert gput(client, tok, "guests/deep", '{"t": ' + "[" * 20 + "]" * 20 + "}").status_code == 200
    assert client.get(f"/api/public/{tok}/c", params={"path": "guests"}).status_code == 200


def test_rate_limit_per_ip_and_link(client, tok, monkeypatch):
    for i in range(public.GUEST_WRITES_PER_IP):
        assert gput(client, tok, f"guests/r{i}", {"i": i}).status_code == 200, i
    r = gput(client, tok, "guests/r31", {"i": 31})
    assert r.status_code == 429
    assert gdel(client, tok, "guests/r0").status_code == 429  # deletes are writes too
    # another IP may go on, until the link has its fill
    public._guest_writes.clear()
    now = 1_000_000.0
    for i in range(public.GUEST_WRITES_PER_LINK):
        assert not public.guest_limited(f"10.0.{i // 250}.{i % 250}", tok, now)
        public.guest_count(f"10.0.{i // 250}.{i % 250}", tok, now)
    assert public.guest_limited("10.9.9.9", tok, now)
    assert not public.guest_limited("10.9.9.9", "another-token", now)
    assert not public.guest_limited("10.9.9.9", tok, now + 3601)  # an hour later
    for _ in range(public.GUEST_WRITES_PER_IP):
        public.guest_count("10.8.8.8", "t2", now)
    assert public.guest_limited("10.8.8.8", "t3", now)
    assert not public.guest_limited("10.8.8.8", "t3", now + 3601)


def test_missing_or_short_secret(hub, client, tok):
    for secret in (None, "short", "x" * 15, "x" * 129, "has space in it 123"):
        r = gput(client, tok, "guests/abc", {"t": 1}, secret=secret)
        assert r.status_code == 400, secret
        assert gdel(client, tok, "guests/abc", secret=secret).status_code == 400, secret
    assert stored(hub, guests_col(), "abc") is None
    assert gput(client, tok, "guests/abc", {"t": 1}, secret="x" * 16).status_code == 200
    assert gput(client, tok, "guests/abd", {"t": 1}, secret="x" * 128).status_code == 200


def test_public_read_single_doc_only(client, tok):
    r = gget(client, tok, "products/k1", route="s")
    assert r.status_code == 200 and r.json() == {"data": {"name": "Kaffe"}}
    assert gget(client, tok, "products/nope", route="s").json() == {"data": None}
    for path in ("products", "other/x", "products/k1/sub/y", "public/abc", "guests/abc", "data/users/x/y",
                 f"{BRANCH}/private/wishes/x", "products/..", "products/", "/products/k1", "products//k1"):
        r = gget(client, tok, path, route="s")
        assert r.status_code in (400, 404), path
        assert "Annet" not in r.text and "Privat" not in r.text
    assert client.get(f"/api/public/{tok}/c", params={"path": "products"}).status_code in (400, 404)
    assert client.get(f"/api/public/{tok}/s/c", params={"path": "products"}).status_code in (404, 405)


def test_added_by_never_reaches_a_guest(hub, client, tok):
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('radar','*','products',?,?,0)",
                    ("k2", json.dumps({"name": "Te", "_added_by": "admin@test.no", "_added_at": 5, "_guest": "h"})))
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('radar',?,?,?,?,0)",
                    (U, public.zone_collection(U, "public", "jul"), "stamped", json.dumps({"_added_by": U, "v": 1})))
    r = gget(client, tok, "products/k2", route="s")
    assert r.json() == {"data": {"name": "Te"}}
    for r in (gget(client, tok, "public/stamped"), client.get(f"/api/public/{tok}/c", params={"path": "public"})):
        assert r.status_code == 200 and "_added_by" not in r.text and U not in r.text


@pytest.mark.parametrize("path", [
    "public/../wishes/x", "public//x", "wishes/x", "agent/track/x", "guests", "public%2F..%2Fx", "public/%2E%2E/x",
    "./public/abc", "public/./abc", "public/../../bursdag/abc", "/public/abc", "public/abc/", "guests/../public/abc",
    "Public/abc", "public/" + "x" * 201, f"{BRANCH}/public/jul/abc", "public/abc/../../bursdag/abc",
])
def test_paths_cannot_leave_the_zone(client, tok, path):
    for r in (gget(client, tok, path), gput(client, tok, path, {"t": 1}), gdel(client, tok, path)):
        assert r.status_code in (400, 403, 404), (path, r.status_code)
        assert "Sykkel" not in r.text and "Hemmelig" not in r.text and "Privat" not in r.text and U not in r.text


def test_encoded_path_in_raw_query(client, tok):
    for raw in ("public%2F..%2Fwishes%2Fx", "public%252F..%252Fx", "public%2F%2Fabc"):
        r = client.get(f"/api/public/{tok}/d?path={raw}")
        assert r.status_code in (400, 404) and "Privat" not in r.text, raw


def test_logged_in_visitor_is_just_a_guest(hub, tok, admin_client, user_client, monkeypatch):
    for c in (admin_client, user_client):  # not even the owner gets more through this API
        assert gput(c, tok, "public/abc", {"title": "x"}).status_code in (403, 404)
        assert gget(c, tok, "public/bursdag/abc").status_code in (400, 404)
        assert gget(c, tok, "other/x", route="s").status_code == 404
    gput(admin_client, tok, "guests/abc", {"t": 1})
    assert stored(hub, guests_col(), "abc")[1]["_guest"] == public.guest_hash(SECRET)
    assert "admin" not in json.dumps(stored(hub, guests_col(), "abc")[1])
    # the session cookie is not read at all
    def boom(*a, **k):
        raise AssertionError("the guest API read the session cookie")
    monkeypatch.setattr(hub.signer, "loads", boom)
    assert gget(admin_client, tok, "public/abc").status_code == 200
    assert gput(admin_client, tok, "guests/def", {"t": 1}).status_code == 200
    assert gdel(admin_client, tok, "guests/def").status_code == 200
    assert gget(admin_client, tok, "products/k1", route="s").status_code == 200


def calls(tok):
    return [lambda c: gget(c, tok, "public/abc"),
            lambda c: c.get(f"/api/public/{tok}/c", params={"path": "public"}),
            lambda c: gput(c, tok, "guests/zz", {"t": 1}),
            lambda c: gdel(c, tok, "guests/zz"),
            lambda c: gget(c, tok, "products/k1", route="s")]


def test_dead_link_is_404_everywhere(hub, client, tok, user_client, monkeypatch):
    def all_404(t):
        for call in calls(t):
            r = call(client)
            assert r.status_code == 404 and U not in r.text, r.text
    all_404("nope")
    all_404(tok + "x")
    hub.set_public("radar", public=False)
    all_404(tok)
    hub.set_public("radar", public=True)
    assert gget(client, tok, "public/abc").status_code == 200
    path = hub._meta_path("radar")
    meta = hub._read_meta(path)
    access.set_level(meta, "admin")
    hub._write_meta(path, meta)
    all_404(tok)
    access.set_level(meta, "all")
    hub._write_meta(path, meta)
    monkeypatch.setattr(hub, "ALLOWED_EMAILS", set())
    all_404(tok)
    monkeypatch.undo()
    assert gget(client, tok, "public/abc").status_code == 200
    old = tok
    share(user_client, action="rotate")
    all_404(old)


def test_response_headers(client, tok):
    want = {"x-robots-tag": "noindex, nofollow", "referrer-policy": "no-referrer", "cache-control": "no-store"}
    responses = [call(client) for call in calls(tok)]
    responses += [call(client) for call in calls("nope")]
    responses += [gget(client, tok, "wishes/x"), gget(client, tok, "public//x"), gput(client, tok, "public/abc", {}),
                  gput(client, tok, "guests/a", {}, secret=None), gput(client, tok, "guests/abc", "x" * 5000),
                  gget(client, tok, "other/x", route="s")]
    for r in responses:
        for k, v in want.items():
            assert r.headers.get(k) == v, (r.request.url, r.status_code, k)


def test_owner_still_blind_after_guest_writes(hub, client, tok, user_client):
    hub.set_public("radar", guests_hidden=True)
    assert gput(client, tok, "guests/abc", {"t": 1}).status_code == 200
    assert gput(client, tok, "guests/abc/replies/r1", {"t": 2}).status_code == 200
    assert user_client.get("/api/store/radar/c", params={"path": f"{BRANCH}/guests/jul"}).json() == {"docs": []}
    assert user_client.get("/api/store/radar/d", params={"path": f"{BRANCH}/guests/jul/abc"}).json() == {"data": None}
    dump = user_client.get("/api/store/radar").json()
    assert not any("/guests/" in col for col in dump)
    # the guest still sees it
    assert gget(client, tok, "guests/abc", secret=SECRET).json()["data"]["_mine"] is True


# ---------------------------------------------------------------- fix round 1
def test_lone_surrogate_is_refused(hub, client, tok):
    for raw in ('{"t": "\\ud800"}', '{"\\udfff": 1}', '{"t": ["ok", {"u": "a\\ud83d"}]}'):
        r = gput(client, tok, "guests/s", raw)
        assert r.status_code == 400, raw
        assert r.headers["cache-control"] == "no-store" and r.headers["x-robots-tag"] == "noindex, nofollow"
    assert stored(hub, guests_col(), "s") is None
    assert gput(client, tok, "guests/s", '{"t": "\\ud83d\\ude00"}').status_code == 200  # a proper pair is fine
    assert gget(client, tok, "guests/s").json()["data"]["t"] == "\U0001F600"


def test_guest_try_checks_and_counts_at_once():
    now = 1_000_000.0
    for _ in range(public.GUEST_WRITES_PER_IP):
        assert public.guest_try("10.1.1.1", "t", now)
    assert not public.guest_try("10.1.1.1", "t", now)
    assert len(public._guest_writes["ip:10.1.1.1"]) == public.GUEST_WRITES_PER_IP  # a refusal counts nothing
    assert public.guest_limited("10.1.1.1", "t", now)
    assert public.guest_try("10.1.1.1", "t", now + 3601)


def test_hub_fields_come_from_one_list():
    data = {"v": 1, "_guest": "h", "_mine": True, "_added_by": "a@t.no", "_added_at": 5}
    assert set(public.HUB_FIELDS) == {"_guest", "_mine", "_added_by", "_added_at"}
    assert public.shared_view(data) == {"v": 1}
    assert public.guest_view(data, "public", None) == {"v": 1, "_added_at": 5}
    assert public.guest_view(data, "guests", public.guest_hash(SECRET)) == {"v": 1, "_added_at": 5, "_mine": False}
    assert public.guest_input(data, "hash", 9) == {"v": 1, "_guest": "hash", "_added_at": 9}
    assert public.owner_view(data) == {"v": 1, "_mine": True, "_added_by": "a@t.no", "_added_at": 5}


CARD = ("async function hubCard({db, user}) { const z = `data/users/${user}/guests/jul`;"
        " const [c, d] = await Promise.all([db.collection(z).get(), db.doc(`${z}/abc`).get()]);"
        " return JSON.stringify([c.docs.map(x => x.data()), d.data()]); }")


def test_owner_never_sees_guest_hash(hub, client, user_client):
    from tests.test_cards import _recipe_app
    _recipe_app(hub, "radar", CARD, shared=True)
    hub.set_public("radar", public=True)
    t = token_of(share(user_client))
    assert gput(client, t, "guests/abc", {"t": 1}).status_code == 200
    assert gput(client, t, "guests/abc/replies/r1", {"t": 2}).status_code == 200
    assert "_guest" in stored(hub, guests_col(), "abc")[1]  # it is kept, only never shown
    col, doc = f"{BRANCH}/guests/jul", f"{BRANCH}/guests/jul/abc"
    seen = [
        user_client.get("/api/store/radar/d", params={"path": doc}).json()["data"],
        user_client.get("/api/store/radar/d", params={"path": f"{doc}/replies/r1"}).json()["data"],
        *[d["data"] for d in user_client.get("/api/store/radar/c", params={"path": col}).json()["docs"]],
        *user_client.get("/api/store/radar").json()[col].values(),
        *user_client.get("/api/store/radar").json()[f"{col}/abc/replies"].values(),
        hub.doc_get("radar", U, doc),
        *hub.doc_list("radar", U, col).values(),
        *hub.doc_list("radar", U, f"{col}/abc/replies").values(),
        *json.loads(hub.card_result(U, "radar", "Europe/Oslo").text)[0],
        json.loads(hub.card_result(U, "radar", "Europe/Oslo").text)[1],
    ]
    assert len(seen) == 10
    for data in seen:
        assert "_guest" not in data and isinstance(data["_added_at"], int) and data["t"] in (1, 2), data
    assert hub.doc_overview("radar", U)[col] == ["abc"]


def test_field_named_guest_elsewhere_is_data(hub, make_page, user_client, admin_client):
    make_shared(hub, make_page, "radar")
    hub.set_public("radar", public=True)
    with hub.db() as con:  # a guests collection of an app without public sharing is an ordinary collection
        make_shared(hub, make_page, "plain")
        for slug, owner, col in (("radar", U, f"{BRANCH}/private/wishes"), ("radar", U, f"{BRANCH}/public/jul"),
                                 ("radar", "*", "products"), ("plain", U, f"{BRANCH}/guests/jul"),
                                 ("radar", U, BRANCH)):
            con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES (?,?,?,'x',?,0)",
                        (slug, owner, col, json.dumps({"_guest": "kept"})))
    for slug, col in (("radar", f"{BRANCH}/private/wishes"), ("radar", f"{BRANCH}/public/jul"), ("radar", "products"),
                      ("plain", f"{BRANCH}/guests/jul"), ("radar", BRANCH)):
        want = {"_guest": "kept"}
        assert user_client.get(f"/api/store/{slug}/d", params={"path": f"{col}/x"}).json()["data"] == want, col
        assert user_client.get(f"/api/store/{slug}/c", params={"path": col}).json()["docs"] == [{"id": "x", "data": want}]
        assert user_client.get(f"/api/store/{slug}").json()[col] == {"x": want}
        assert hub.doc_get(slug, U, f"{col}/x") == want
        assert hub.doc_list(slug, U, col) == {"x": want}
    # a personal app has no zones at all
    make_page("solo")
    with hub.db() as con:
        con.execute("INSERT INTO docs(slug, owner, collection, doc_id, data, updated_at) VALUES ('solo',?,?,'x',?,0)",
                    (U, "guests/jul", json.dumps({"_guest": "kept"})))
    assert user_client.get("/api/store/solo").json() == {"guests/jul": {"x": {"_guest": "kept"}}}
