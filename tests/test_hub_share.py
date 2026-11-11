"""window.claude.use("share") in hub.js, run in V8 (py_mini_racer) with a stubbed browser; asserts on what fetch receives."""
import json
from pathlib import Path

import pytest
from py_mini_racer import MiniRacer

HUB_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "hub.js").read_text(encoding="utf-8")

OWNER = {"slug": "wishes", "user": "me@test.no", "shared": "1", "public": "1", "publicRead": "products"}
GUEST = {"slug": "wishes", "guest": "1", "token": "tok123", "shareName": "list1", "publicRead": "products"}

STUBS = """
const CALLS = [];
let RESPOND = (call) => ({ status: 200, body: { data: null, docs: [] } });
globalThis.window = globalThis;
globalThis.document = { currentScript: { dataset: DATASET }, hidden: false, readyState: "complete",
  addEventListener() {}, querySelector() { return null; } };
globalThis.addEventListener = () => {};
globalThis.matchMedia = () => ({ matches: false });
globalThis.navigator = {};
globalThis.sessionStorage = { getItem() { return null; }, setItem() {} };
globalThis.location = { pathname: "/", href: "/", reload() { CALLS.push({ reload: true }); } };
globalThis.setInterval = () => 0;
globalThis.setTimeout = (fn) => { Promise.resolve().then(fn); return 0; };
let seed = 0;
globalThis.crypto = { getRandomValues(a) { for (let i = 0; i < a.length; i++) a[i] = (seed++ * 37 + 11) % 256; return a; } };
const STORE = {};
globalThis.localStorage = STORAGE_BROKEN
  ? { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } }
  : { getItem: (k) => (k in STORE ? STORE[k] : null), setItem: (k, v) => { STORE[k] = v; } };
globalThis.fetch = async (url, opts) => {
  const call = { url, method: opts.method, headers: opts.headers || {}, body: opts.body === undefined ? null : JSON.parse(opts.body) };
  CALLS.push(call);
  const r = RESPOND(call);
  if (r.fail) throw new Error("offline");
  return { ok: r.status < 400, status: r.status, redirected: false, url, json: async () => r.body };
};
"""


def run(dataset, body, storage_broken=False):
    """Run an async JS body against hub.js loaded with `dataset` as the script tag's data attributes.

    The body can `return` JSON-able values and set RESPOND; returns (result, recorded fetch calls)."""
    ctx = MiniRacer()
    prelude = f"const DATASET = {json.dumps(dataset)}; const STORAGE_BROKEN = {json.dumps(storage_broken)};"
    ctx.eval(prelude + STUBS + HUB_JS)  # loading it here is also the syntax check of hub.js
    out = ctx.eval(f"(async () => {{ {body} }})().then((r) => JSON.stringify({{ r: r === undefined ? null : r, calls: CALLS }}))")
    parsed = json.loads(out.get(timeout=5))
    return parsed["r"], parsed["calls"]


def test_share_null_without_public():
    res, calls = run({"slug": "x", "user": "me@test.no"}, "return await window.claude.use('share');")
    assert res is None and calls == []


def test_existing_capabilities_unchanged_without_public():
    res, _ = run({"slug": "x", "user": "me@test.no"},
                 "return [!!(await claude.use('db')), !!(await claude.use('user')), !!(await claude.use('downloads')), '__share' in claude];")
    assert res == [True, True, True, False]


def test_owner_paths_map_into_branch():
    res, calls = run(OWNER, """
      const share = await claude.use('share');
      await share.db.doc('public/abc').get();
      await share.db.collection('guests/g1/sub').get();
      await share.db.doc('public/abc').set({ a: 1 });
      await share.db.doc('guests/x').delete();
      return [share.mode, share.name];""")
    assert res == ["owner", "main"]
    base = "/api/store/wishes"
    assert [(c["method"], c["url"]) for c in calls] == [
        ("GET", base + "/d?path=data%2Fusers%2Fme%40test.no%2Fpublic%2Fmain%2Fabc"),
        ("GET", base + "/c?path=data%2Fusers%2Fme%40test.no%2Fguests%2Fmain%2Fg1%2Fsub"),
        ("PUT", base + "/d?path=data%2Fusers%2Fme%40test.no%2Fpublic%2Fmain%2Fabc"),
        ("DELETE", base + "/d?path=data%2Fusers%2Fme%40test.no%2Fguests%2Fmain%2Fx"),
    ]
    assert calls[2]["body"] == {"a": 1}
    assert all("X-Hub-Guest" not in c["headers"] for c in calls)


def test_guest_paths_use_public_api_and_secret_header():
    res, calls = run(GUEST, """
      RESPOND = (c) => ({ status: 200, body: c.url.includes('/c?') ? { docs: [{ id: 'a', data: { n: 1, _mine: true } }] } : { data: { n: 1 } } });
      const share = await claude.use('share');
      const snap = await share.db.collection('guests').get();
      await share.db.doc('guests/w1').set({ n: 1 });
      await share.db.doc('guests/w1').delete();
      await share.db.doc('public/item').get();
      return [share.mode, share.name, snap.docs.map((d) => d.data())];""")
    assert res == ["guest", "list1", [{"n": 1, "_mine": True}]]
    base = "/api/public/tok123"
    assert [(c["method"], c["url"]) for c in calls] == [
        ("GET", base + "/c?path=guests"),
        ("PUT", base + "/d?path=guests%2Fw1"),
        ("DELETE", base + "/d?path=guests%2Fw1"),
        ("GET", base + "/d?path=public%2Fitem"),
    ]
    secrets = {c["headers"]["X-Hub-Guest"] for c in calls}
    assert len(secrets) == 1 and len(next(iter(secrets))) == 32
    assert all(not c["url"].startswith("/api/store") and "list1" not in c["url"] for c in calls)


@pytest.mark.parametrize("dataset", [OWNER, GUEST])
def test_other_paths_rejected_without_request(dataset):
    res, calls = run(dataset, """
      const share = await claude.use('share');
      const codes = [];
      for (const f of [() => share.db.doc('notes/a').get(), () => share.db.collection('private').get(),
                       () => share.db.doc('notes/a').set({}), () => share.db.doc('notes/a').delete()]) {
        try { await f(); codes.push('resolved'); } catch (e) { codes.push(e.code); }
      }
      return codes;""")
    assert res == ["invalid_argument"] * 4
    assert calls == []


def test_scope_switches_name_and_returns_db():
    res, calls = run(OWNER, """
      const share = await claude.use('share');
      const scoped = share.scope('list-7', 'Christmas');
      await scoped.doc('public/a').get();
      await share.db.doc('public/a').get();
      return [share.name, { ...claude.__share }];""")
    assert res == ["list-7", {"name": "list-7", "title": "Christmas"}]
    assert calls[0]["url"].endswith("public%2Flist-7%2Fa")
    assert calls[1]["url"].endswith("public%2Flist-7%2Fa")  # share.db follows the current name


def test_scope_keeps_earlier_db_on_its_own_name():
    _, calls = run(OWNER, """
      const share = await claude.use('share');
      const a = share.scope('one', 'One');
      share.scope('two', 'Two');
      await a.doc('public/x').get();""")
    assert calls[0]["url"].endswith("public%2Fone%2Fx")


def test_scope_rejects_bad_names():
    res, calls = run(OWNER, """
      const share = await claude.use('share');
      const codes = [];
      for (const n of ['', 'a/b', 'a b', 'x'.repeat(65), '..', 5]) {
        try { share.scope(n, 't'); codes.push('ok'); } catch (e) { codes.push(e.code); }
      }
      return [codes, share.name];""")
    assert res == [["invalid_argument"] * 6, "main"]


def test_remove_turns_link_off_for_owner_only():
    res, calls = run(OWNER, "const share = await claude.use('share'); await share.remove('list-7'); return 1;")
    assert calls == [{"url": "/api/share/wishes", "method": "POST", "headers": {"Content-Type": "application/json"},
                      "body": {"name": "list-7", "action": "off"}}]
    res, calls = run(GUEST, """
      const share = await claude.use('share'); const codes = [];
      try { await share.remove('x'); } catch (e) { codes.push(e.code); }
      try { share.scope('x', 't'); } catch (e) { codes.push(e.code); }
      return codes;""")
    assert res == ["invalid_argument"] * 2 and calls == []


def test_guest_mode_has_no_db_or_user():
    res, calls = run(GUEST, """
      return [await claude.use('db'), await claude.use('user'), !!(await claude.use('downloads')), !!(await claude.use('share'))];""")
    assert res == [None, None, True, True] and calls == []


def test_shared_is_single_doc_get_only():
    res, calls = run(GUEST, """
      RESPOND = () => ({ status: 200, body: { data: { name: 'K' } } });
      const share = await claude.use('share');
      const snap = await share.shared.doc('products/k1').get();
      return [Object.keys(share.shared), Object.keys(share.shared.doc('products/k1')), snap.exists, snap.data()];""")
    assert res == [["doc"], ["get"], True, {"name": "K"}]
    assert calls[0]["url"] == "/api/public/tok123/s?path=products%2Fk1"
    assert calls[0]["headers"]["X-Hub-Guest"]
    res, calls = run(OWNER, "const share = await claude.use('share'); await share.shared.doc('products/k1').get(); return 1;")
    assert calls[0]["url"] == "/api/store/wishes/d?path=products%2Fk1"


def test_shared_rejects_collection_paths():
    res, _ = run(GUEST, """
      const share = await claude.use('share');
      try { share.shared.doc('products'); return 'ok'; } catch (e) { return e instanceof TypeError; }""")
    assert res is True


def test_secret_is_stored_and_reused():
    res, calls = run(GUEST, """
      const share = await claude.use('share');
      await share.db.doc('guests/a').get(); await share.db.doc('guests/b').get();
      return [localStorage.getItem('hub_guest')];""")
    h = calls[0]["headers"]["X-Hub-Guest"]
    assert res == [h] and calls[1]["headers"]["X-Hub-Guest"] == h
    assert len(h) == 32 and all(ch in "0123456789abcdef" for ch in h)


@pytest.mark.parametrize("stored", ["short", "A" * 32, "g" * 32, "a" * 31, "a" * 33, " " + "a" * 31, ""])
def test_a_stored_secret_of_the_wrong_shape_is_replaced(stored):
    res, calls = run(GUEST, f"""
      localStorage.setItem('hub_guest', {json.dumps(stored)});
      const share = await claude.use('share');
      await share.db.doc('guests/a').get(); await share.db.doc('guests/b').get();
      return [localStorage.getItem('hub_guest')];""")
    h = calls[0]["headers"]["X-Hub-Guest"]
    assert h != stored and len(h) == 32 and all(ch in "0123456789abcdef" for ch in h)
    assert res == [h] and calls[1]["headers"]["X-Hub-Guest"] == h


def test_a_stored_secret_of_the_right_shape_is_kept():
    _, calls = run(GUEST, """
      localStorage.setItem('hub_guest', '0123456789abcdef0123456789abcdef');
      const share = await claude.use('share'); await share.db.doc('guests/a').get();""")
    assert calls[0]["headers"]["X-Hub-Guest"] == "0123456789abcdef0123456789abcdef"


def test_secret_survives_storage_failure():
    _, calls = run(GUEST, """
      const share = await claude.use('share');
      await share.db.doc('guests/a').get(); await share.db.doc('guests/b').get();""", storage_broken=True)
    a, b = (c["headers"]["X-Hub-Guest"] for c in calls)
    assert a == b and len(a) == 32


def test_guest_error_codes_and_no_login_redirect():
    res, calls = run(GUEST, """
      const share = await claude.use('share'); const out = [];
      for (const status of [429, 403, 404, 413, 500, 'net']) {
        RESPOND = () => status === 'net' ? { fail: true } : { status, body: { detail: 'x' } };
        try { await share.db.doc('guests/a').set({}); } catch (e) { out.push(e.code); }
      }
      return out;""")
    assert res == ["resource_exhausted", "invalid_argument", "invalid_argument", "invalid_argument", "unavailable", "unavailable"]
    assert not any(c.get("reload") for c in calls)


def test_owner_429_is_unchanged():
    res, _ = run(OWNER, """
      RESPOND = () => ({ status: 429, body: {} });
      const share = await claude.use('share');
      try { await share.db.doc('public/a').get(); } catch (e) { return e.code; }""")
    assert res == "unavailable"


def test_share_object_is_frozen():
    res, _ = run(GUEST, "const s = await claude.use('share'); 'use strict'; try { s.mode = 'owner'; } catch (e) {} return s.mode;")
    assert res == "guest"


# ---------------------------------------------------------------- final review
def test_guest_update_rejected_without_request():
    res, calls = run(GUEST, """
      const share = await claude.use('share'); const out = [];
      for (const ref of [share.db.doc('guests/a'), share.db.collection('guests').doc('b'), share.db.doc('public/c')]) {
        try { await ref.update({ n: 1 }); out.push('resolved'); } catch (e) { out.push(e.code); }
      }
      return out;""")
    assert res == ["invalid_argument"] * 3 and calls == []
    _, calls = run(OWNER, "const share = await claude.use('share'); await share.db.doc('public/a').update({ n: 1 }); return 1;")
    assert calls[0]["method"] == "PUT" and calls[0]["url"].endswith("public%2Fmain%2Fa&merge=1")


@pytest.mark.parametrize("dataset", [OWNER, GUEST])
def test_shared_reads_only_public_read_collections(dataset):
    res, calls = run(dataset, """
      const share = await claude.use('share'); const out = [];
      for (const p of ['other/x', 'products/k1/notes/n1', 'productsx/k1', 'data/users']) {
        try { await share.shared.doc(p).get(); out.push('resolved'); } catch (e) { out.push(e.code); }
      }
      await share.shared.doc('products/k1').get();
      return out;""")
    assert res == ["invalid_argument"] * 4
    assert len(calls) == 1 and calls[0]["url"].endswith("path=products%2Fk1")
    res, calls = run({**dataset, "publicRead": ""}, """
      const share = await claude.use('share');
      try { await share.shared.doc('products/k1').get(); return 'resolved'; } catch (e) { return e.code; }""")
    assert res == "invalid_argument" and calls == []
