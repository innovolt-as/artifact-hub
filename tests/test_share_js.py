"""static/share.js (the banner's share sheet), run in V8 (py_mini_racer) with a stubbed browser: the request helper
that the sheet's buttons go through, and that a page without the banner's sheet is left alone."""
import json
from pathlib import Path

from py_mini_racer import MiniRacer

SHARE_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "share.js").read_text(encoding="utf-8")

STUBS = """
const CALLS = [];
let RESPOND = () => ({ status: 200, body: { link: null, guest_docs: 0, locked: false } });
globalThis.window = globalThis;
globalThis.document = { currentScript: { dataset: { slug: "wishes", strings: "{}" } }, readyState: "complete",
  querySelector() { return null; }, addEventListener() {} };
globalThis.navigator = {};
globalThis.fetch = async (url, opts) => {
  CALLS.push({ url, method: opts.method || "GET", body: opts.body === undefined ? null : JSON.parse(opts.body) });
  const r = RESPOND();
  if (r.fail) throw new Error("offline");
  return { ok: r.status < 400, status: r.status, json: async () => r.body };
};
"""


def run(body):
    ctx = MiniRacer()
    ctx.eval(STUBS + SHARE_JS)  # loading it here is also the syntax check; with no banner init() does nothing
    out = ctx.eval(f"(async () => {{ {body} }})().then((r) => JSON.stringify({{ r: r === undefined ? null : r, calls: CALLS }}))")
    parsed = json.loads(out.get(timeout=5))
    return parsed["r"], parsed["calls"]


def test_reads_the_state_of_one_name():
    res, calls = run("return await hubShare.request('wishes', 'jul list');")
    assert res == {"ok": True, "state": {"link": None, "guest_docs": 0, "locked": False}}
    assert calls == [{"url": "/api/share/wishes?name=jul%20list", "method": "GET", "body": None}]


def test_an_action_posts_name_and_action():
    res, calls = run("return await hubShare.request('wishes', 'main', { action: 'create', title: 'Jul' });")
    assert res["ok"] is True
    assert calls == [{"url": "/api/share/wishes", "method": "POST",
                      "body": {"name": "main", "action": "create", "title": "Jul"}}]


def test_a_locked_app_is_told_apart_from_other_failures():
    res, _ = run("RESPOND = () => ({ status: 423, body: {} }); return await hubShare.request('wishes', 'main', { action: 'off' });")
    assert res == {"ok": False, "locked": True}
    res, _ = run("RESPOND = () => ({ status: 500, body: {} }); return await hubShare.request('wishes', 'main');")
    assert res == {"ok": False, "locked": False}
    res, _ = run("RESPOND = () => ({ fail: true }); return await hubShare.request('wishes', 'main');")
    assert res == {"ok": False, "locked": False}
