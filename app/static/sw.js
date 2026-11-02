// The hub's service worker (served at /sw.js, scope /). It keeps copies on the phone so the front page and the apps
// marked «Virker uten nett» open without a connection:
//   hub-pages-v1   the front page (/), each marked app's page (/a/<slug>/) and the files it fetches from its folder,
//                  and the state under /__hub/state: {"user": "<e-mail>", "offline": ["<slug>", ...]}
//   hub-static-v1  /static/*, /icon/*, /manifest.webmanifest, and the Google Fonts a marked app uses
// A copy is only ever something the server sent, never an app's data, and all copies belong to one user. Pages say
// who is logged in and what is marked: hub:home from the front page (home.js), hub:app from every app page (hub.js),
// and hub:forget from forget.js, which deletes the copies on logged-out pages and after «Slett mine data».
// The server gets WAIT_MS to answer before a copy is used. A request not handled below gets no respondWith and goes to
// the network as if this worker were not there.
const PAGES = "hub-pages-v1", STATIC = "hub-static-v1";
const STATE = "/__hub/state";
const WAIT_MS = 3000;
// Never answered from here, also when a marked app asks: the API, logging in and out, settings, admin, the code
// screen, the OAuth pages and the Claude connector
const SKIP = ["/api/", "/login", "/auth", "/logout", "/password", "/settings", "/admin", "/lock/", "/oauth/", "/mcp",
  "/authorize", "/token", "/register", "/revoke", "/.well-known/"];
const FONTS = ["fonts.googleapis.com", "fonts.gstatic.com"];
const PRECACHE = { "X-Hub-Precache": "1" }; // serve_artifact: the page as it opens, not counted as a visit

const here = (path) => new URL(path, self.location.origin).href;
const pageOf = (slug) => here(`/a/${slug}/`);
const isSlug = (s) => typeof s === "string" && /^[a-z0-9][a-z0-9._-]{0,80}$/.test(s); // SLUG_RE in app/main.py
const isHubFile = (path) => path.startsWith("/static/") || path.startsWith("/icon/") || path === "/manifest.webmanifest";
const fine = (r) => r.status === 200 && r.type === "basic" && !r.redirected; // never a redirect, an error or opaque
const isHtml = (r) => (r.headers.get("Content-Type") || "").startsWith("text/html");
const copyOf = (cacheName, url) => caches.match(url, { cacheName, ignoreVary: true }); // creates no cache
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ------------------------------------------------------------------ state
let state = null; // {user, offline}, as stored; null until it has been read after the worker started
let gen = 0; // goes up when the copies are wiped, so an answer asked for before is never stored after
const ready = readState().then((s) => { state ||= s; });
let chain = ready; // changes to the caches and the state, one at a time
function queue(task) {
  const run = chain.then(() => task());
  chain = run.catch(() => {});
  return run;
}

async function readState() {
  try {
    const s = await (await copyOf(PAGES, here(STATE)))?.json();
    if (s && typeof s.user === "string" && Array.isArray(s.offline)) return { user: s.user, offline: s.offline.filter(isSlug) };
  } catch { /* unreadable: start empty */ }
  return { user: "", offline: [] };
}
async function saveState() {
  const cache = await caches.open(PAGES);
  await cache.put(here(STATE), new Response(JSON.stringify(state), { headers: { "Content-Type": "application/json" } }));
}

// Store an answer, unless the copies were wiped since it was asked for, nobody is logged in (a logged-out page
// fetching the hub's files must not bring the caches back), or, for an app's file, the app is no longer marked
function store(cacheName, url, res, g, slug) {
  return queue(async () => {
    if (g !== gen || !state.user || (slug && !state.offline.includes(slug))) return;
    await (await caches.open(cacheName)).put(url, res);
  }).catch(() => {}); // storage full, or the answer broke off: not stored
}

// Every hub-* cache, and nothing else on the phone
async function wipe(user) {
  gen++;
  state = { user, offline: [] };
  for (const name of await caches.keys()) if (name.startsWith("hub-")) await caches.delete(name);
}

async function dropCopies(slug) { // the app's page and folder files
  if (!(await caches.has(PAGES))) return;
  const cache = await caches.open(PAGES), prefix = pageOf(slug);
  for (const req of await cache.keys()) if (req.url.startsWith(prefix)) await cache.delete(req);
}
async function dropApp(slug) {
  state.offline = state.offline.filter((s) => s !== slug);
  if (state.user) await saveState();
  await dropCopies(slug);
}

// ------------------------------------------------------------------ install, activate
self.addEventListener("install", (e) => e.waitUntil(self.skipWaiting()));
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const name of await caches.keys()) {
    if (name.startsWith("hub-") && name !== PAGES && name !== STATIC) await caches.delete(name);
  }
  await self.clients.claim();
})()));

// ------------------------------------------------------------------ messages from the pages
self.addEventListener("message", (e) => {
  const m = e.data || {};
  if (m.type === "hub:forget") e.waitUntil(queue(() => wipe("")).catch(() => {}));
  else if ((m.type === "hub:home" || m.type === "hub:app") && typeof m.user === "string" && m.user) {
    e.waitUntil(update(m).catch(() => {})); // storage full: the copies stay as they were
  }
});

async function update(m) {
  const list = m.type === "hub:home" ? (Array.isArray(m.offline) ? m.offline.filter(isSlug) : []) : null;
  if (!list && !isSlug(m.slug)) return;
  const g = await queue(async () => {
    state = await readState(); // forget.js may have deleted the caches since
    if (state.user !== m.user) await wipe(m.user); // someone else's copies go first
    if (list) {
      for (const slug of state.offline) if (!list.includes(slug)) await dropCopies(slug);
      state.offline = list;
    } else if (m.offline) {
      if (!state.offline.includes(m.slug)) state.offline.push(m.slug);
    } else {
      state.offline = state.offline.filter((s) => s !== m.slug);
      await dropCopies(m.slug);
    }
    await saveState();
    return gen;
  });
  const assets = new Set(Array.isArray(m.assets) ? m.assets.filter((u) => typeof u === "string") : []);
  const jobs = [...assets].map((u) => keepHubFile(u, g));
  if (list) jobs.push(keepFront(g), ...list.map((slug) => precache(slug, g)));
  else if (m.offline) jobs.push(precache(m.slug, g));
  await Promise.all(jobs);
}

// The hub's files the page uses, also when the worker did not control it yet (the first visit)
async function keepHubFile(u, g) {
  let url;
  try { url = new URL(u); } catch { return; }
  if (url.origin !== self.location.origin || !isHubFile(url.pathname) || (await copyOf(STATIC, url.href))) return;
  try {
    const r = await fetch(url.href, { credentials: "same-origin" });
    if (fine(r)) await store(STATIC, url.href, r, g);
  } catch { /* offline: next time */ }
}

// The front page itself when there is no copy: on the first visit it loaded before the worker was there, and another
// user's copy may just have been wiped
async function keepFront(g) {
  if (await copyOf(PAGES, here("/"))) return;
  try {
    const r = await fetch("/", { credentials: "same-origin", cache: "no-store" });
    if (fine(r) && isHtml(r)) await store(PAGES, here("/"), r, g);
  } catch { /* offline */ }
}

// A fresh copy of a marked app's page. 404 (no longer marked or visible), 423 (locked) or a redirect (the login page)
// deletes its copies; no network or a server error keeps what is there.
async function precache(slug, g) {
  let r;
  try {
    r = await fetch(pageOf(slug), { credentials: "same-origin", cache: "no-store", headers: PRECACHE });
  } catch { return; }
  if (r.redirected || r.status === 404 || r.status === 423) await queue(() => g === gen && dropApp(slug));
  else if (fine(r) && isHtml(r)) await store(PAGES, pageOf(slug), r, g, slug);
}

// ------------------------------------------------------------------ requests
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) {
    if (FONTS.includes(url.hostname)) font(e, url);
    return;
  }
  const path = url.pathname, nav = req.mode === "navigate";
  if (SKIP.some((p) => path.startsWith(p))) return;
  if (path === "/") {
    e.respondWith(nav ? front(e, url) : frontFresh(e, url));
    return;
  }
  const app = path.match(/^\/a\/([^/]+)\/(.*)$/);
  if (app) appFile(e, app[1], app[2], nav);
  else if (isHubFile(path) && !nav) e.respondWith(hubFile(e, url));
});

// The network's answer, unless it does not come within WAIT_MS, fails, or is a server error (Caddy's 502 while the hub
// is upgraded): then the copy, if there is one, else the network's answer however late. `answer` sees every network
// answer, also one that comes after the copy was used.
async function networkFirst(e, copy, answer) {
  const net = fetch(e.request);
  e.waitUntil(net.then(answer).catch(() => {}));
  const first = await Promise.race([net, sleep(WAIT_MS)]).catch(() => null);
  if (first && first.status < 500) return first;
  return (await copy()) || net;
}

// Opening the front page: the copy is marked data-hub-offline="1" for home.js. A redirect (the login page, when the
// login has run out) and a 4xx go through as they are, and only a 200 page is stored ("/?pw=changed" is a one-off).
function front(e, url) {
  const g = gen;
  return networkFirst(e, async () => {
    const copy = await copyOf(PAGES, here("/"));
    if (!copy) return undefined;
    const html = (await copy.text()).replace("<html", '<html data-hub-offline="1"');
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }, (r) => { if (!url.search && fine(r) && isHtml(r)) return store(PAGES, here("/"), r.clone(), g); });
}

// home.js fetching the front page to refresh it in place: always the network, never the copy
async function frontFresh(e, url) {
  const g = gen, r = await fetch(e.request);
  if (!url.search && fine(r) && isHtml(r)) e.waitUntil(store(PAGES, here("/"), r.clone(), g));
  return r;
}

// Under /a/<slug>/, only for a marked app. Its page comes from the network, else the copy hub:home or hub:app stored
// (an opened page is not stored: the copy is the pre-cache one); opening it to a redirect, 404 or 423 deletes the
// copies. Its other files come from the network and are stored, with the stored one as the fallback.
function appFile(e, slug, rest, nav) {
  const marked = state ? state.offline.includes(slug) : null; // null: the worker has just started
  if (marked === false) return;
  e.respondWith((async () => {
    if (marked === null) {
      await ready;
      if (!state.offline.includes(slug)) return fetch(e.request); // not marked after all: as from the network
    }
    const g = gen, url = e.request.url;
    if (rest === "" || rest === "index.html") {
      return networkFirst(e, () => copyOf(PAGES, pageOf(slug)), (r) => {
        if (nav && (r.type === "opaqueredirect" || r.redirected || r.status === 404 || r.status === 423)) {
          return queue(() => g === gen && dropApp(slug));
        }
        return undefined;
      });
    }
    return networkFirst(e, () => copyOf(PAGES, url), (r) => { if (fine(r)) return store(PAGES, url, r.clone(), g, slug); });
  })());
}

// The hub's own files. With ?v= the address changes with the file, so a stored one is used at once; without it the
// network's comes first.
async function hubFile(e, url) {
  const g = gen, keep = async (r) => { if (fine(r)) await store(STATIC, url.href, r.clone(), g); };
  if (url.searchParams.has("v")) {
    const copy = await copyOf(STATIC, url.href);
    if (copy) return copy;
    const r = await fetch(e.request);
    e.waitUntil(keep(r));
    return r;
  }
  return networkFirst(e, () => copyOf(STATIC, url.href), keep);
}

// Google Fonts on a marked app's page: stored the first time, then used from the store. A stylesheet loaded without
// crossorigin gives an opaque answer, which is kept too.
function font(e, url) {
  if (!e.clientId || (state && !state.offline.length)) return;
  e.respondWith((async () => {
    await ready;
    const client = await self.clients.get(e.clientId);
    const m = client && new URL(client.url).pathname.match(/^\/a\/([^/]+)\//);
    if (!m || !state.offline.includes(m[1])) return fetch(e.request);
    const g = gen, copy = await copyOf(STATIC, url.href);
    if (copy) return copy;
    const r = await fetch(e.request);
    if ((r.status === 200 && !r.redirected) || r.type === "opaque") e.waitUntil(store(STATIC, url.href, r.clone(), g));
    return r;
  })());
}
