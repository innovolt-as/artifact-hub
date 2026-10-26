/*
 * hub.js — injected into every HTML artifact served by the hub.
 *
 * Artifacts built on claude.ai reach storage etc. through window.claude.use(name). That runtime
 * only exists inside claude.ai, so this file provides a compatible subset here:
 *   db        -> documents stored on the hub, private per artifact AND per logged-in user
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
  const API = `/api/store/${encodeURIComponent(SLUG)}`;
  const POLL_MS = 5000;
  // Texts come from the hub's language files as a JSON block right before this script; without it the key shows.
  let S = {};
  try { S = JSON.parse(document.getElementById("__hub_strings").textContent); } catch (e) { /* use the keys */ }
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
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      const code = { 400: "invalid_argument", 404: "invalid_argument", 413: "invalid_argument" }[r.status] || "unavailable";
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
    can: async () => true,
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
