// The hub's service worker (served at /sw.js, scope /). It keeps copies on the phone so the front page and the apps
// marked «Works offline» open without a connection:
//   hub-pages-v1   the front page (/), each marked app's page (/a/<slug>/) and the files it fetches from its folder,
//                  and the state under /__hub/state: {"user": "<e-mail>", "offline": ["<slug>", ...]}
//   hub-static-v1  /static/*, /icon/*, /manifest.webmanifest, and the Google Fonts a marked app uses
// A copy is only ever something the server sent, never an app's data, and all copies belong to one user. Pages say
// who is logged in and what is marked: hub:home from the front page (home.js), hub:app from every app page (hub.js),
// and hub:forget from forget.js, which deletes the copies on logged-out pages and after «Delete my data». A request
// that logs someone in (a magic link, the login or password form) wipes the copies before the page it leads to.
// The server gets WAIT_MS to answer before a copy is used; once it has not, the network counts as down for DOWN_MS and
// the files a page loads come from their copies at once. A request not handled below gets no respondWith and goes to
// the network as if this worker were not there, and so does one whose handler fails.
const PAGES = "hub-pages-v1", STATIC = "hub-static-v1";
const STATE = "/__hub/state";
const WAIT_MS = 3000;
const DOWN_MS = 30000;
// Never answered from here, also when a marked app asks: the API, logging in and out, settings, admin, the code
// screen, the OAuth pages and the Claude connector
const SKIP = ["/api/", "/login", "/auth", "/logout", "/password", "/settings", "/admin", "/lock/", "/oauth/", "/mcp",
  "/authorize", "/token", "/register", "/revoke", "/.well-known/"];
// Requests that set a login: a magic link (GET /auth) and the login and password forms (POST). Someone else may be
// logging in on this phone without a logged-out page in between, so the copies go before the page they lead to.
const LOGINS = [["GET", "/auth"], ["POST", "/login"], ["POST", "/password"]];
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
// A navigation passed on from here reaches the server as Sec-Fetch-Dest: empty. serve_artifact gives only a page opened
// in the tab the banner and the code screen, so say what it is ("document", or "iframe" for a frame).
function forward(req) {
  if (req.mode !== "navigate") return req;
  try {
    const headers = new Headers(req.headers);
    headers.set("X-Hub-Dest", req.destination);
    return new Request(req, { headers });
  } catch {
    return req; // a browser that will not build one: as it is
  }
}

// ------------------------------------------------------------------ state
let state = null; // {user, offline}, as stored; null until it has been read after the worker started
let gen = 0; // goes up when the copies are wiped, so an answer asked for before is never stored after
const ready = readState().then((s) => { state ||= s; });
let chain = ready; // changes to the caches and the state, one at a time
let wiping = ready; // the last wipe asked for; a page copy is only read after it
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
// fetching the hub's files must not bring the caches back), or, for an app's file, the app is no longer marked. The
// body is read before the queue, so one that stalls holds up nothing; an opaque answer (a font stylesheet loaded
// without crossorigin) cannot be read here, and its put gets WAIT_MS in the queue.
async function store(cacheName, url, res, g, slug) {
  try {
    const opaque = res.type === "opaque";
    const kept = opaque ? res
      : new Response(await res.arrayBuffer(), { status: res.status, statusText: res.statusText, headers: res.headers });
    await queue(async () => {
      if (g !== gen || !state.user || (slug && !state.offline.includes(slug))) return;
      const put = (await caches.open(cacheName)).put(url, kept);
      put.catch(() => {});
      await (opaque ? Promise.race([put, sleep(WAIT_MS)]) : put);
    });
  } catch { /* storage full, or the answer broke off: not stored */ }
}

// Every hub-* cache, and nothing else on the phone
async function wipe(user) {
  gen++;
  state = { user, offline: [] };
  for (const name of await caches.keys()) if (name.startsWith("hub-")) await caches.delete(name);
}

function wipeSoon() {
  wiping = queue(() => wipe(""));
  return wiping.catch(() => {});
}
// A page's copy, read only once a wipe asked for before has run (a login lands on / straight after its request)
async function pageCopy(url) {
  await wiping.catch(() => {});
  return copyOf(PAGES, url);
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
  if (m.type === "hub:forget") e.waitUntil(wipeSoon());
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
  const own = m.type === "hub:app" && m.offline ? m.slug : null;
  const jobs = [...assets].map((u) => keepFile(u, g, own));
  if (list) jobs.push(keepFront(g, false), ...list.map((slug) => precache(slug, g)));
  else {
    // An app's home-screen icon has storage of its own, where the banner's link to / finds no copy unless one is kept
    // from here (not from the stored copy of the app: that is not someone opening it)
    if (!m.copy) jobs.push(keepFront(g, true));
    if (m.offline) jobs.push(precache(m.slug, g));
  }
  await Promise.all(jobs);
}

// A file the page uses, also when the worker did not control it yet (the first visit): the hub's own, and for a marked
// app (`own`) the files from its folder, never another app's and never its page (that copy is the pre-cache one)
async function keepFile(u, g, own) {
  let url;
  try { url = new URL(u); } catch { return; }
  url.hash = "";
  if (url.origin !== self.location.origin) return;
  const mine = own && url.href.startsWith(pageOf(own)) && url.href !== pageOf(own) && url.pathname !== `/a/${own}/index.html`;
  const cacheName = isHubFile(url.pathname) ? STATIC : mine ? PAGES : null;
  if (!cacheName || (await copyOf(cacheName, url.href))) return;
  try {
    const r = await fetch(url.href, { credentials: "same-origin" });
    if (fine(r)) await store(cacheName, url.href, r, g, mine ? own : undefined);
  } catch { /* offline: next time */ }
}

// The front page itself when there is no copy: on the first visit it loaded before the worker was there, another
// user's copy may just have been wiped, or the page is an app opened from its own home-screen icon. From an app page
// (`withFiles`) also the hub's files the front page loads, which the front page itself sends with hub:home.
async function keepFront(g, withFiles) {
  if (await copyOf(PAGES, here("/"))) return;
  try {
    const r = await fetch("/", { credentials: "same-origin", cache: "no-store" });
    if (!fine(r) || !isHtml(r)) return;
    const html = withFiles ? await r.clone().text() : "";
    await store(PAGES, here("/"), r, g);
    const files = html.matchAll(/(?:href|src)="(\/(?:static\/|icon\/|manifest\.webmanifest)[^"]*)"/g);
    await Promise.all([...files].map((f) => keepFile(here(f[1].replaceAll("&amp;", "&")), g, null)));
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
  const url = new URL(req.url);
  if (url.origin === self.location.origin && LOGINS.some(([m, p]) => req.method === m && url.pathname === p)) {
    e.waitUntil(wipeSoon()); // watched only: the request itself goes to the network as it is
    return;
  }
  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) {
    if (FONTS.includes(url.hostname)) font(e, url);
    return;
  }
  const path = url.pathname, nav = req.mode === "navigate";
  if (SKIP.some((p) => path.startsWith(p))) return;
  if (path === "/") {
    respond(e, () => (nav ? front(e, url) : frontFresh(e, url)));
    return;
  }
  const app = path.match(/^\/a\/([^/]+)\/(.*)$/);
  if (app) appFile(e, app[1], app[2], nav);
  else if (isHubFile(path) && !nav) respond(e, () => hubFile(e, url));
});

// Every answer from here: if anything in this worker fails, the request goes to the network (named as forward() does,
// so an app's page still gets its banner and code screen)
function respond(e, handler) {
  const answer = (async () => handler())(); // runs at once, as before; a throw becomes a rejection
  e.respondWith(answer.catch(() => fetch(forward(e.request))));
}

// The network counts as down until downUntil, from the moment it did not answer within WAIT_MS or failed. Only an
// answer that comes in time ends it early: a late one is still a network that makes every file wait.
let downUntil = 0;
const isDown = () => Date.now() < downUntil;
function fromNetwork(req) {
  const asked = Date.now();
  return fetch(req).then((r) => {
    if (Date.now() - asked < WAIT_MS) downUntil = 0;
    return r;
  });
}

// The network's answer, unless it does not come within WAIT_MS, fails, or is a server error (Caddy's 502 while the hub
// is upgraded): then the copy, if there is one, else the network's answer however late. `answer` sees every network
// answer, also one that comes after the copy was used.
async function networkFirst(e, copy, answer, req = e.request) {
  const net = fromNetwork(req);
  e.waitUntil(net.then(answer).catch(() => {}));
  const first = await Promise.race([net, sleep(WAIT_MS)]).catch(() => null);
  if (first && first.status < 500) return first;
  if (!first && !req.signal?.aborted) downUntil = Date.now() + DOWN_MS; // not when the page itself gave up the request
  return (await copy()) || net;
}

// A file a page loads: while the network is down its copy at once, with the network's answer stored in the background;
// otherwise as networkFirst. Pages themselves always ask the network first.
async function copyFirst(e, copy, answer, req = e.request) {
  const stored = isDown() && (await copy());
  if (!stored) return networkFirst(e, copy, answer, req);
  e.waitUntil(fromNetwork(req).then(answer).catch(() => {}));
  return stored;
}

// Opening the front page: the copy is marked data-hub-offline="1" for home.js. A redirect (the login page, when the
// login has run out) and a 4xx go through as they are, and only a 200 page is stored ("/?pw=changed" is a one-off).
function front(e, url) {
  const g = gen;
  return networkFirst(e, async () => {
    const copy = await pageCopy(here("/"));
    if (!copy) return undefined;
    const html = (await copy.text()).replace("<html", '<html data-hub-offline="1"');
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }, (r) => { if (!url.search && fine(r) && isHtml(r)) return store(PAGES, here("/"), r.clone(), g); });
}

// home.js fetching the front page to refresh it in place: always the network, never the copy
async function frontFresh(e, url) {
  const g = gen, r = await fromNetwork(e.request);
  if (!url.search && fine(r) && isHtml(r)) e.waitUntil(store(PAGES, here("/"), r.clone(), g));
  return r;
}

// Under /a/<slug>/, only for a marked app. Its page comes from the network, else the copy hub:home or hub:app stored
// (an opened page is not stored: the copy is the pre-cache one); opening it to a redirect, 404 or 423 deletes the
// copies. Its other files come from the network and are stored, with the stored one as the fallback (copyFirst).
function appFile(e, slug, rest, nav) {
  const marked = state ? state.offline.includes(slug) : null; // null: the worker has just started
  if (marked === false) return;
  respond(e, async () => {
    if (marked === null) {
      await ready;
      if (!state.offline.includes(slug)) return fetch(forward(e.request)); // not marked after all: as from the network
    }
    const g = gen, url = e.request.url;
    if (rest === "" || rest === "index.html") {
      return networkFirst(e, () => pageCopy(pageOf(slug)), (r) => {
        if (nav && (r.type === "opaqueredirect" || r.redirected || r.status === 404 || r.status === 423)) {
          return queue(() => g === gen && dropApp(slug));
        }
        return undefined;
      }, forward(e.request));
    }
    return copyFirst(e, () => pageCopy(url), (r) => { if (fine(r)) return store(PAGES, url, r.clone(), g, slug); },
      forward(e.request));
  });
}

// The hub's own files. With ?v= the address changes with the file, so a stored one is used at once; without it the
// network's comes first, unless the network is down (copyFirst).
async function hubFile(e, url) {
  const g = gen, keep = async (r) => { if (fine(r)) await store(STATIC, url.href, r.clone(), g); };
  if (url.searchParams.has("v")) {
    const copy = await copyOf(STATIC, url.href);
    if (copy) return copy;
    const r = await fetch(e.request);
    e.waitUntil(keep(r));
    return r;
  }
  return copyFirst(e, () => copyOf(STATIC, url.href), keep);
}

// Google Fonts on a marked app's page: stored the first time, then used from the store. A stylesheet loaded without
// crossorigin gives an opaque answer, which is kept too.
function font(e, url) {
  if (!e.clientId || (state && !state.offline.length)) return;
  respond(e, async () => {
    await ready;
    const client = await self.clients.get(e.clientId);
    const m = client && new URL(client.url).pathname.match(/^\/a\/([^/]+)\//);
    if (!m || !state.offline.includes(m[1])) return fetch(e.request);
    const g = gen, copy = await copyOf(STATIC, url.href);
    if (copy) return copy;
    const r = await fetch(e.request);
    if ((r.status === 200 && !r.redirected) || r.type === "opaque") e.waitUntil(store(STATIC, url.href, r.clone(), g));
    return r;
  });
}
