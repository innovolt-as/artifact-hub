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


# A page with the banner's sheet: a minimal DOM that records what the script builds
PAGE_STUBS = """
const CALLS = [];
let RESPOND = () => ({ status: 200, body: { link: null, guest_docs: 0, locked: false, ready: false } });
globalThis.window = globalThis;
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; this.found = {}; }
  append(...k) { this.kids.push(...k); }
  replaceChildren(...k) { this.kids = k; }
  setAttribute() {}
  addEventListener(t, f) { this.on[t] = f; }
  querySelector(s) { return this.found[s] || null; }
  get textContent() { return this.own; }
  set textContent(v) { this.own = v; }
}
const button = new El("button"), sheet = new El("dialog"), body = new El("div"), x = new El("button");
sheet.found = { ".body": body, ".x": x };
sheet.showModal = () => {};
const host = { shadowRoot: new El("root") };
host.shadowRoot.found = { "button.share": button, "dialog.sheet": sheet };
globalThis.document = { currentScript: { dataset: { slug: "wishes", strings: JSON.stringify({ not_ready: "NOT READY", explain: "EXPLAIN" }) } },
  readyState: "complete", querySelector: (s) => (s === "hub-banner" ? host : null), addEventListener() {},
  createElement: (t) => new El(t) };
globalThis.navigator = {};
globalThis.fetch = async (url, opts) => {
  CALLS.push(url);
  const r = RESPOND();
  return { ok: r.status < 400, status: r.status, json: async () => r.body };
};
"""


def open_sheet(state):
    ctx = MiniRacer()
    ctx.eval(PAGE_STUBS + SHARE_JS)
    ctx.eval(f"RESPOND = () => ({{ status: 200, body: {json.dumps(state)} }});")
    out = ctx.eval("(async () => { button.on.click(); for (let i = 0; i < 20; i++) await Promise.resolve();"
                   " return JSON.stringify(body.kids.map((k) => [k.className || '', k.own || ''])); })()")
    return json.loads(out.get(timeout=5))


def test_the_sheet_warns_when_the_app_is_not_written_for_sharing():
    kids = open_sheet({"link": None, "guest_docs": 0, "locked": False, "ready": False})
    assert ["warn", "NOT READY"] in kids


def test_the_sheet_is_quiet_for_a_ready_app_and_for_an_answer_without_the_flag():
    assert not any(k[0] == "warn" for k in open_sheet({"link": None, "guest_docs": 0, "locked": False, "ready": True}))
    assert not any(k[0] == "warn" for k in open_sheet({"link": None, "guest_docs": 0, "locked": False}))
