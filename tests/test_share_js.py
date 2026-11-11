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


SHEET_STUBS = """
const HANDLERS = {};
let CLOSED = 0;
const node = (name) => ({ addEventListener(type, fn) { HANDLERS[name + ":" + type] = fn; }, replaceChildren() {},
  querySelector(sel) { return NODES[sel] || null; } });
const NODES = { ".body": node("body"), ".x": node("x"), "button.share": node("button") };
const SHEET = Object.assign(node("sheet"), { close() { CLOSED++; },
  getBoundingClientRect: () => ({ left: 100, top: 50, right: 300, bottom: 400 }) });
NODES["dialog.sheet"] = SHEET;
NODES["hub-banner"] = { shadowRoot: { querySelector: (sel) => NODES[sel] || null } };
globalThis.document.querySelector = (sel) => NODES[sel] || null;
"""


def test_only_a_tap_outside_the_sheet_closes_it():
    ctx = MiniRacer()
    ctx.eval(STUBS + SHEET_STUBS + SHARE_JS)
    out = ctx.eval("""(() => {
      const click = HANDLERS["sheet:click"], seen = [];
      for (const [x, y, target, detail] of [[150, 60, SHEET], [101, 399, SHEET], [200, 200, NODES[".x"]],
                                            [50, 200, NODES[".x"]], [50, 200, SHEET], [200, 450, SHEET],
                                            [50, 200, SHEET, 0], [0, 0, SHEET, 0], [0, 0, SHEET, 1], [50, 200, SHEET, 1]]) {
        const before = CLOSED;
        click({ clientX: x, clientY: y, target, detail });
        seen.push(CLOSED > before);
      }
      return JSON.stringify(seen);
    })()""")
    # inside the dialog's own box (its padding) or on a child: stays open; on the dim area around it: closes. A click
    # with no pointer position (from the keyboard: detail 0, or both coordinates 0) stays open
    assert json.loads(out) == [False, False, False, False, True, True, False, False, False, True]
