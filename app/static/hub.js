/*
 * hub.js — injected into every HTML artifact served by the hub.
 *
 * Artifacts built on claude.ai reach storage etc. through window.claude.use(name). That runtime
 * only exists inside claude.ai, so this file provides a compatible subset here:
 *   db        -> documents stored on the hub, per artifact and per logged-in user; in an app with shared
 *                data (data-shared="1") shared by everyone who can see it, written by admins only, except each
 *                user's own data/users/<e-mail>/ branch, which stays private (as on claude.ai); collections named in
 *                data-append are open for everyone to add documents to, not to change or delete
 *   downloads -> save({filename, data}) as a plain browser download
 *   user      -> who is viewing (the logged-in e-mail)
 * Other capabilities (sample, room, mcp, ...) resolve null, which artifacts must handle anyway.
 */
(function () {
  if (window.claude && window.claude.__hub) return;
  const me = document.currentScript;
  const SLUG = me.dataset.slug;
  const EMAIL = me.dataset.user;
  const ADMIN = me.dataset.admin === "1";
  const SHARED = me.dataset.shared === "1";
  const APPEND = (me.dataset.append || "").split(",").filter(Boolean);  // add-only collections of a shared app
  const API = `/api/store/${encodeURIComponent(SLUG)}`;
  const POLL_MS = 5000;
  // Texts come from the hub's language files as data-strings on this script tag; without them the key shows.
  let S = {};
  try { S = JSON.parse(me.dataset.strings); } catch (e) { /* use the keys */ }
  const fmt = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
  const tr = (key, vars) => fmt(S[key] || key, vars);

  // ------------------------------------------------------------------ helpers
  const dbError = (code, message) => Object.assign(new Error(message), { code, message });

  async function api(method, url, body) {
    let r;
    try {
      r = await fetch(url, {
        method,
        headers: body !== undefined ? { "Content-Type": "application/json" } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "same-origin",
      });
    } catch (e) {
      throw dbError("unavailable", tr("network"));
    }
    if (r.redirected && new URL(r.url).pathname === "/login") {
      location.href = "/login?next=" + encodeURIComponent(location.pathname);
      throw dbError("unavailable", tr("not_logged_in"));
    }
    if (r.status === 423) { location.reload(); throw dbError("unavailable", tr("locked")); } // the code screen takes over
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      // claude.ai has no permission code; a refused write (403) cannot succeed on retry either
      const code = { 400: "invalid_argument", 403: "invalid_argument", 404: "invalid_argument", 413: "invalid_argument" }[r.status] || "unavailable";
      throw dbError(code, j.detail || tr("error_status", { status: r.status }));
    }
    return r.json();
  }

  const segs = (p) => String(p).split("/").filter(Boolean);
  function checkPath(path, wantEven) {
    const s = segs(path);
    if (!s.length || (s.length % 2 === 0) !== wantEven) {
      throw new TypeError(tr(wantEven ? "bad_doc_path" : "bad_col_path", { path }));
    }
    return s.join("/");
  }
  const newId = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/-/g, "");
  const META = Object.freeze({ fromCache: false, hasPendingWrites: false });

  function docSnap(id, data) {
    const body = data === undefined ? undefined : Object.freeze(data);
    return { id, exists: body !== undefined, data: () => body, metadata: META };
  }

  // ------------------------------------------------------------------ subscriptions (polling)
  const subs = new Set(); // {key, fetch: () => Promise<any>, deliver(result)}
  async function refresh(sub) {
    try { sub.deliver(await sub.fetch()); }
    catch (e) { if (sub.error) sub.error(e); }
  }
  function refreshAll() { subs.forEach(refresh); }
  setInterval(() => { if (!document.hidden) refreshAll(); }, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });
  function subscribe(fetcher, deliver, error) {
    const sub = { fetch: fetcher, deliver, error };
    subs.add(sub);
    refresh(sub);
    return () => subs.delete(sub);
  }

  // ------------------------------------------------------------------ code lock (data-lock="1")
  // The hub keeps a locked app open for 10 minutes after the last ping, so ping while the page shows. The clock here
  // is what locks a page that has lost the network or has been in the background: reload without waiting for an answer.
  if (me.dataset.lock === "1") {
    const PING_MS = 60000, OPEN_MS = 600000;
    let last = Date.now();
    // Hide the body, not <html>: the canvas keeps the page background instead of flashing white.
    const lock = () => { (document.body || document.documentElement).style.visibility = "hidden"; location.reload(); };
    const late = () => Date.now() - last >= OPEN_MS;
    async function ping() {
      try {
        const r = await fetch(`/api/lock/${encodeURIComponent(SLUG)}/ping`, { method: "POST", credentials: "same-origin" });
        if (r.status === 423 || r.status === 401) return lock();
        if (r.ok) last = Date.now();
      } catch (e) { /* no network: the deadline decides */ }
    }
    const check = () => { if (late()) lock(); else if (!document.hidden) ping(); };
    setInterval(check, PING_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
    addEventListener("pageshow", check);
  }

  // ------------------------------------------------------------------ back to the front page after 2 minutes away
  // The hub as a home-screen app: coming back after a while should show the front page, not the app left behind.
  // Only when the session started at the front page (hub-start) and the page is not asking to stay (hubStay).
  let stay = false;
  window.hubStay = (on) => { stay = !!on; };
  // Text the user typed and has not saved keeps the page too: record typed fields, forget them on submit.
  const typed = new Set();
  const isField = (el) => el instanceof Element && !el.closest("hub-banner") && (el.isContentEditable || el.tagName === "TEXTAREA"
    || (el.tagName === "INPUT" && /^(text|search|email|url|tel|number|password|date|time|datetime-local|month|week)$/.test(el.type)));
  document.addEventListener("input", (e) => { if (isField(e.target)) typed.add(e.target); }, true);
  document.addEventListener("submit", (e) => { for (const el of e.target.elements || []) typed.delete(el); }, true);
  const holdsText = () => {
    try {
      return [...typed].some((el) => el.isConnected && el.getClientRects().length > 0
        && (el.isContentEditable ? el.textContent !== "" : el.value !== "" && el.value !== el.defaultValue));
    } catch (e) { return true; } // an error in the check means stay: never lose text
  };
  try {
    if (!sessionStorage.getItem("hub-start")) sessionStorage.setItem("hub-start", location.pathname);
    const standalone = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
    if (standalone && sessionStorage.getItem("hub-start") === "/") {
      const AWAY_MS = 120000;
      let left = null;
      const back = () => {
        if (left !== null && !stay && Date.now() - left >= AWAY_MS && !holdsText()) location.replace("/");
        left = null;
      };
      document.addEventListener("visibilitychange", () => { if (document.hidden) left = Date.now(); else back(); });
      addEventListener("pageshow", back);
    }
  } catch (e) { /* no sessionStorage: the rule does not apply */ }

  // ------------------------------------------------------------------ the copy on the phone (static/sw.js)
  // The hub's service worker keeps the page of an app marked «Works offline» (data-offline="1"), and the files it
  // uses, and drops the copy of one that is not. Once the page has loaded, tell it, with those files (it did not see
  // them load on the first visit), and whether this is its stored copy (data-copy="1"). Not through
  // navigator.serviceWorker.ready: under an app with its own worker, that is the app's. Without service workers the app
  // works as before.
  async function hubWorker(sw) {
    const reg = await sw.register("/sw.js");
    const next = reg.installing || reg.waiting;
    if (next) {
      await new Promise((resolve) => {
        const done = () => { if (next.state === "activated" || next.state === "redundant") resolve(); };
        next.addEventListener("statechange", done);
        done();
      });
    }
    return reg.active;
  }
  try {
    const sw = navigator.serviceWorker;
    if (sw) {
      const parsed = document.readyState === "loading"
        ? new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, { once: true })) : null;
      Promise.all([hubWorker(sw), parsed]).then(([worker]) => {
        const roots = [document, document.querySelector("hub-banner")?.shadowRoot].filter(Boolean);
        const assets = roots.flatMap((r) => [...r.querySelectorAll("link[rel=stylesheet], script[src], img[src]")])
          .map((el) => el.href || el.src).filter((u) => u && u.startsWith(location.origin + "/"));
        worker?.postMessage({ type: "hub:app", user: EMAIL, slug: SLUG, offline: me.dataset.offline === "1", assets,
          copy: me.dataset.copy === "1" });
      }).catch(() => {});
    }
  } catch (e) { /* no service workers here */ }

  // ------------------------------------------------------------------ queries
  const OPS = {
    "==": (a, b) => a === b, "!=": (a, b) => a !== b,
    "<": (a, b) => a < b, "<=": (a, b) => a <= b, ">": (a, b) => a > b, ">=": (a, b) => a >= b,
    "in": (a, b) => b.includes(a), "not-in": (a, b) => !b.includes(a),
    "array-contains": (a, b) => Array.isArray(a) && a.includes(b),
  };

  function makeQuery(path, filters, order, max) {
    async function run() {
      const { docs } = await api("GET", `${API}/c?path=${encodeURIComponent(path)}`);
      let list = docs.filter((d) => filters.every(([f, op, v]) => f in d.data && OPS[op](d.data[f], v)));
      if (order) {
        const [f, dir] = order, k = dir === "desc" ? -1 : 1;
        list.sort((x, y) => {
          if (!(f in x.data)) return 1;
          if (!(f in y.data)) return -1;
          return x.data[f] < y.data[f] ? -k : x.data[f] > y.data[f] ? k : 0;
        });
      }
      if (max) list = list.slice(0, max);
      return list.map((d) => docSnap(d.id, d.data));
    }
    function querySnap(docs, prev) {
      const changes = [];
      const prevIdx = new Map((prev || []).map((d, i) => [d.id, i]));
      docs.forEach((d, i) => {
        if (!prevIdx.has(d.id)) changes.push({ type: "added", doc: d, oldIndex: -1, newIndex: i });
        else if (JSON.stringify(prev[prevIdx.get(d.id)].data()) !== JSON.stringify(d.data()))
          changes.push({ type: "modified", doc: d, oldIndex: prevIdx.get(d.id), newIndex: i });
      });
      const now = new Set(docs.map((d) => d.id));
      (prev || []).forEach((d, i) => { if (!now.has(d.id)) changes.push({ type: "removed", doc: d, oldIndex: i, newIndex: -1 }); });
      return { docs, size: docs.length, empty: docs.length === 0, docChanges: () => changes, metadata: META, forEach: (fn) => docs.forEach(fn) };
    }
    return {
      where: (f, op, v) => {
        if (!OPS[op]) throw new TypeError(tr("unknown_op", { op }));
        return makeQuery(path, [...filters, [f, op, v]], order, max);
      },
      orderBy: (f, dir = "asc") => makeQuery(path, filters, [f, dir], max),
      limit: (n) => makeQuery(path, filters, order, n),
      get: async () => querySnap(await run()),
      onSnapshot(next, error) {
        let prev = null, last = null;
        return subscribe(run, (docs) => {
          const key = JSON.stringify(docs.map((d) => [d.id, d.data()]));
          if (key === last) return; // only deliver real changes
          last = key;
          const snap = querySnap(docs, prev);
          prev = docs;
          next(snap);
        }, error);
      },
    };
  }

  // ------------------------------------------------------------------ references
  function docRef(path) {
    path = checkPath(path, true);
    const id = path.split("/").pop();
    const url = `${API}/d?path=${encodeURIComponent(path)}`;
    const get = async () => docSnap(id, (await api("GET", url)).data ?? undefined);
    const write = async (method, u, body) => { await api(method, u, body); refreshAll(); };
    return {
      id, path,
      get,
      set: (data) => write("PUT", url, data),
      update: (data) => write("PUT", url + "&merge=1", data),
      delete: () => write("DELETE", url),
      acquire: async () => ({ acquired: true, expiresAt: new Date(Date.now() + 30000).toISOString() }), // one user per store
      onSnapshot(next, error) {
        let last;
        return subscribe(get, (snap) => {
          const key = JSON.stringify(snap.data() ?? null);
          if (key === last) return;
          last = key;
          next(snap);
        }, error);
      },
      collection: (sub) => collectionRef(path + "/" + sub),
    };
  }

  function collectionRef(path) {
    path = checkPath(path, false);
    return Object.assign(makeQuery(path, [], null, 0), {
      path,
      doc: (id) => docRef(path + "/" + (id || newId())),
      async add(data) { const ref = docRef(path + "/" + newId()); await ref.set(data); return ref; },
    });
  }

  const db = Object.freeze({ doc: docRef, collection: collectionRef });

  // ------------------------------------------------------------------ downloads
  const downloads = Object.freeze({
    async save({ filename, data }) {
      if (!filename || data == null) throw Object.assign(new Error(tr("save_args")), { code: "bad_request" });
      const blob = data instanceof Blob ? data : new Blob([data]);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      return { status: "saved" };
    },
  });

  // ------------------------------------------------------------------ user
  const hue = [...EMAIL].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
  const profile = { id: EMAIL, name: EMAIL.split("@")[0], avatarUrl: "", color: `hsl(${hue} 55% 48%)`, email: EMAIL, isMe: true, guest: false };
  const user = Object.freeze({
    isOwner: async () => ADMIN,
    canEdit: async () => ADMIN,
    can: async (name) => {
      if (name === "data.write") return !SHARED || ADMIN;
      if (typeof name === "string" && name.startsWith("data.add:")) return !SHARED || ADMIN || APPEND.includes(name.slice(9));
      return true;
    },
    id: async () => EMAIL,
    me: async () => ({ id: EMAIL, name: profile.name, avatarUrl: "", color: profile.color, email: EMAIL, isOwner: ADMIN, canEdit: ADMIN }),
    profiles: async (ids) => Object.fromEntries([].concat(ids).map((i) => [i, i === EMAIL ? profile : { id: i, name: "", avatarUrl: "", color: "", email: null, isMe: false, guest: false }])),
    name: async () => profile.name,
    avatarUrl: async () => null,
    email: async () => EMAIL,
    search: async () => [profile],
  });

  // ------------------------------------------------------------------ window.claude
  const caps = { db, downloads, user };
  window.claude = Object.freeze({
    __hub: true,
    use: (name) => new Promise((resolve) => setTimeout(() => resolve(caps[name] || null), 0)),
  });
})();
