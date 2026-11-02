// Front page: greeting and date from the viewer's clock, view toggle, pinning (star in the card view,
// long-press / right-click menu in the icon view) and the "Choose apps" list. Prefs live on the account
// (/api/prefs/*). The page never reloads: it fetches itself again, swaps in what changed and blinks those cards.
//
// Groups fold and unfold on a tap (toggleGroup); the choice is saved on the account like the other prefs.
//
// Shared with pull.js and drag.js:
//   window.hubRefresh() -> Promise<boolean>  true when the page was updated, false when fetching it failed
//   "hub:menu" on document, detail {li, x, y} opens the pin/unpin menu (drag.js: long press on a favourite)
//   "hub:idle" on document                    a drag or the menu is done, so a waiting refresh may run
//   <html data-hub-drag="1">                  set by drag.js while a favourite is being dragged
//   window.hubDragJustEnded() -> boolean      drag.js: a tap that ends a drag must not fold the group under it
(function () {
  const root = document.documentElement;
  const picker = document.getElementById("picker");
  const S = JSON.parse(document.getElementById("__hub_strings").textContent);
  const failed = () => alert(S.save_failed);
  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  // #home is swapped on refresh, so every listener sits on document and finds its element with closest()
  const at = (e, sel) => (e.target instanceof Element ? e.target.closest(sel) : null);
  let menu = null; // the open pin/unpin menu
  let current = null, fetching = false, queued = null; // the refresh under way, whether its fetch has left, the next one

  function stamp() {
    const now = new Date(), h = now.getHours();
    document.getElementById("hello").textContent =
      S.greet[h < 5 ? 0 : h < 10 ? 1 : h < 12 ? 2 : h < 18 ? 3 : 4];
    document.getElementById("today").textContent =
      now.toLocaleDateString(S.locale, { weekday: "long", day: "numeric", month: "long" });
  }
  stamp();
  try { if (!sessionStorage.getItem("hub-start")) sessionStorage.setItem("hub-start", location.pathname); } catch (e) { /* none */ }

  // ------------------------------------------------------------ refresh in place
  const keyOf = (li) => (li.closest("section")?.id || "") + "/" + li.dataset.slug;
  const cardsOf = (home) => new Map([...home.querySelectorAll("li.app[data-slug]")].map((li) => [keyOf(li), li]));
  // What the server drew: each card's HTML by section/slug, and the rest of #home with the cards as placeholders
  // (sections, slug order, the dot on "Choose apps"...). Taken from server markup only, never from the live page,
  // so classes like blink or a drag's inline styles don't count as changes. Whether a group is open is kept out of the
  // frame (open: group id -> "1"/"0"): a fold, here or in another tab, is applied to the live group and neither swaps
  // #home nor blinks a card.
  const groupsOf = (home) => [...home.querySelectorAll("section.group[data-group]")];
  function snapshot(home) {
    const frame = home.cloneNode(true);
    frame.querySelectorAll("li.app[data-slug]").forEach((li) => li.replaceWith("[" + li.dataset.slug + "]"));
    groupsOf(frame).forEach((g) => {
      g.removeAttribute("data-open");
      g.querySelector(".gtoggle")?.removeAttribute("aria-expanded");
      g.querySelector("ul")?.removeAttribute("hidden");
      g.querySelector(".gclosed")?.remove();
    });
    return {
      cards: new Map([...cardsOf(home)].map(([k, li]) => [k, li.outerHTML])),
      open: new Map(groupsOf(home).map((g) => [g.dataset.group, g.dataset.open])),
      frame: frame.outerHTML,
      view: home.querySelector(".apps")?.dataset.view,
    };
  }
  let shown = snapshot(document.getElementById("home"));

  // ------------------------------------------------------------ folding groups
  // Group id -> "1"/"0" for a fold whose save is under way; refreshes leave those groups as they are
  const folding = new Map();
  // A closed group shows its apps as one row of small icons, copied from its cards (the server draws the same row for
  // a group that was closed when the page was fetched)
  function syncClosed(section) {
    let row = section.querySelector(".gclosed");
    if (section.dataset.open === "1") {
      const had = row && row === document.activeElement; // the row goes away: keep keyboard focus in the group
      row?.remove();
      if (had) section.querySelector(".gtoggle")?.focus({ preventScroll: true });
      return;
    }
    if (!row) {
      row = document.createElement("button");
      row.type = "button";
      row.className = "gclosed";
      row.setAttribute("aria-expanded", "false");
      row.setAttribute("aria-label", section.querySelector(".gtoggle")?.getAttribute("aria-label") || "");
      section.append(row);
    }
    row.replaceChildren(...[...section.querySelectorAll("li.app .icon")].map((ic) => {
      const c = ic.cloneNode(true);
      c.classList.add("icon-xs");
      c.setAttribute("aria-hidden", "true");
      return c;
    }));
  }
  function setOpen(section, open) {
    section.dataset.open = open ? "1" : "0";
    section.querySelector(".gtoggle")?.setAttribute("aria-expanded", String(open));
    const list = section.querySelector("ul");
    if (list) list.hidden = !open;
    syncClosed(section);
  }
  // Flips at once, saves, and flips back (with the usual alert) if the save fails
  function toggleGroup(section) {
    if (offline()) return; // nothing saves offline
    const id = section.dataset.group, open = section.dataset.open !== "1";
    setOpen(section, open);
    folding.set(id, open ? "1" : "0");
    const wanted = open ? "1" : "0";
    const done = () => { if (folding.get(id) === wanted) folding.delete(id); };
    post("/api/prefs/groups/open", { id, open }).then(
      () => refresh({ after: true }).finally(done),
      () => {
        const latest = folding.get(id) === wanted; // a later toggle of this group has its own save to answer for
        done();
        const now = document.getElementById("g-" + id); // #home may have been swapped meanwhile
        if (now && latest) setOpen(now, !open);
        failed();
      },
    );
  }

  const pressView = (view) =>
    document.querySelectorAll("[data-set-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setView === view)));

  // force: swap the whole #home, whatever is unchanged (the offline layout has moved the cards around)
  function apply(doc, quiet, force = false) {
    const fresh = doc.getElementById("home");
    const next = snapshot(fresh);
    const redrawn = [...cardsOf(fresh)].filter(([k]) => shown.cards.get(k) !== next.cards.get(k)); // new here or changed
    let home = document.getElementById("home");
    const live = cardsOf(home);
    const focused = document.activeElement;
    const focusLi = focused && home.contains(focused) ? focused.closest("li.app") : null;
    let swapped, redrawnGroups;
    if (!force && next.frame === shown.frame && redrawn.every(([k]) => live.has(k))) {
      swapped = redrawn.map(([k, li]) => { // same layout: only the changed cards
        const n = document.importNode(li, true);
        live.get(k).replaceWith(n);
        return n;
      });
      for (const g of groupsOf(home)) if (swapped.some((n) => g.contains(n))) syncClosed(g); // its icons changed
    } else {
      const n = document.importNode(fresh, true);
      home.replaceWith(n);
      home = n;
      const now = cardsOf(n);
      swapped = redrawn.map(([k]) => now.get(k));
    }
    // Open or closed as the server has it, except a group folded here whose save has not been answered yet
    for (const g of groupsOf(home)) {
      const want = folding.has(g.dataset.group) ? folding.get(g.dataset.group) : next.open.get(g.dataset.group);
      if (want && g.dataset.open !== want) setOpen(g, want === "1");
    }
    // A new view redraws every card; that is not a change to blink about
    if (!quiet && !(shown.view && next.view && shown.view !== next.view)) swapped.forEach((li) => li.classList.add("blink"));
    shown = next;
    if (focusLi && !focusLi.isConnected) { // keep keyboard focus on the same card after its node was replaced
      const li = [...home.querySelectorAll("li.app")].find((x) => x.dataset.slug === focusLi.dataset.slug);
      li?.querySelector(focused.matches(".pin") ? ".pin" : "a")?.focus({ preventScroll: true });
    }

    const view = doc.querySelector('[data-set-view][aria-pressed="true"]');
    if (view) pressView(view.dataset.setView);
    const list = "#picker .sheet-in > ul, #picker .sheet-in > p.none";
    const oldList = document.querySelector(list), newList = doc.querySelector(list);
    if (!picker.open && oldList && newList) oldList.replaceWith(document.importNode(newList, true));
    const strings = doc.getElementById("__hub_strings");
    if (strings) Object.assign(S, JSON.parse(strings.textContent));
    stamp();
  }

  // Wait while a favourite is dragged, the pin menu is open or "Choose apps" is open; each of them sends hub:idle
  // and, while offline, a finger on the screen
  let touching = 0;
  const offline = () => root.dataset.hubOffline === "1";
  const busy = () => !!(root.dataset.hubDrag || menu || picker.open || (offline() && touching));
  const idle = () =>
    new Promise((resolve) => {
      if (!busy()) return resolve();
      const check = () => {
        if (busy()) return;
        document.removeEventListener("hub:idle", check);
        resolve();
      };
      document.addEventListener("hub:idle", check);
    });

  async function run(quiet) {
    // Busy again by the time this resumes, e.g. drag.js opens the menu as it lets go: wait on
    do { await idle(); } while (busy());
    fetching = true;
    // A fetch that hangs on a weak connection would be shared by every refresh after it: give up after 10 s, and the
    // next refresh asks again
    const ctl = window.AbortController ? new AbortController() : null;
    const timer = ctl && setTimeout(() => ctl.abort(), 10000);
    let doc;
    try {
      const r = await fetch("/", { credentials: "same-origin", cache: "no-store", signal: ctl?.signal });
      if (r.status >= 500) goOffline(); // the server is down: as offline, like the service worker
      if (r.status !== 200) return false;
      doc = new DOMParser().parseFromString(await r.text(), "text/html");
    } catch {
      goOffline(); // no network, or no answer within 10 s
      return false;
    } finally {
      clearTimeout(timer);
    }
    if (!doc.getElementById("home")) return false; // e.g. the login page after the session ran out
    do { await idle(); } while (busy()); // don't move cards under a finger: something may have started while fetching
    try {
      const back = offline(); // the copy is showing and the server answered: draw the real page, without blinking
      apply(doc, quiet || back, back);
      if (back) leaveOffline();
    } catch (e) {
      console.error(e);
      return false;
    }
    return true;
  }

  // One refresh at a time. A call while one is under way shares it, unless the caller has just changed something
  // on the server (after) and that fetch already left; then one more runs when it is done.
  function refresh({ after = false, quiet = false } = {}) {
    if (current && !(after && fetching)) return current;
    if (current) return (queued ||= current.then(() => { queued = null; return refresh({ after, quiet }); }));
    current = run(quiet).finally(() => { current = null; fetching = false; });
    return current;
  }
  window.hubRefresh = () => refresh();

  // Back on the page: from another tab or app, or from the browser's back/forward cache. A page that was open when the
  // network went (the usual way back into a home-screen app) shows layout C at once without a network, or when the
  // server has not answered within 3 s; a later answer draws the real page again.
  function check() {
    if (navigator.onLine === false) goOffline();
    const slow = offline() ? null : setTimeout(goOffline, 3000);
    refresh().finally(() => clearTimeout(slow));
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  addEventListener("pageshow", (e) => { if (e.persisted || offline()) check(); });

  // ------------------------------------------------------------ the stored front page (layout C)
  // The service worker answers with its copy of this page and sets data-hub-offline on <html>; an open page that loses
  // the server sets it itself (goOffline). Only apps marked
  // «Works offline» and found in the hub's cache can open, so they get a section of their own and the rest is greyed.
  // Nothing here saves anything: the stars, the view toggle and «Choose apps» are hidden (hub.css) and guarded below.
  let toast = null, toastTimer = null;
  function showToast(text) {
    toast?.remove();
    clearTimeout(toastTimer);
    toast = document.createElement("div");
    toast.className = "hub-toast";
    toast.setAttribute("role", "status");
    toast.textContent = text;
    document.body.append(toast);
    toastTimer = setTimeout(() => { toast?.remove(); toast = null; }, 2500);
  }
  function leaveOffline() {
    delete root.dataset.hubOffline;
    document.querySelector(".offline-badge")?.remove();
    clearTimeout(toastTimer);
    toast?.remove();
    toast = null;
  }
  // The open page lost the server: mark it at once (hub.css hides what saves), and rearrange it once nothing is being
  // dragged or touched
  async function goOffline() {
    if (offline()) return;
    root.dataset.hubOffline = "1";
    try {
      do { await idle(); } while (busy());
      if (offline()) await enterOffline();
    } catch (e) {
      console.error(e);
    }
  }
  async function enterOffline() {
    const bar = document.querySelector(".topbar .hero-row");
    if (bar && !bar.querySelector(".offline-badge")) {
      const badge = document.createElement("span");
      badge.className = "offline-badge";
      const dot = document.createElement("span");
      dot.className = "d";
      badge.append(dot, S.offline_badge);
      bar.append(badge);
    }
    const apps = document.querySelector("#home .apps");
    if (!apps) return;
    // Favourites, every group (open or closed: its hidden cards count too) and the rest, in page order
    const pageSections = "#fav, section.group, #rest";
    const cards = [...apps.querySelectorAll(pageSections)].flatMap((s) => [...s.querySelectorAll("li.app")]);
    const marked = new Set(S.offline_apps || []);
    const stored = await Promise.all(cards.map(async (li) => {
      if (!marked.has(li.dataset.slug)) return false;
      // only the hub's cache: an app's own (Treningsprogram's sbfb-*) may hold the same address
      try { return !!(await caches.match("/a/" + li.dataset.slug + "/", { cacheName: "hub-pages-v1" })); } catch { return false; }
    }));
    if (!offline() || !apps.isConnected) return; // the server answered meanwhile
    const kind = apps.dataset.view === "icons" ? "grid" : "cards";
    const section = (id, title, items, caption) => {
      if (!items.length) return null;
      const sec = document.createElement("section");
      sec.id = id;
      const h = document.createElement("h3");
      h.className = "sec";
      h.textContent = title;
      const ul = document.createElement("ul");
      ul.className = kind;
      ul.append(...items);
      sec.append(h);
      if (caption) {
        sec.className = "offsec";
        const p = document.createElement("p");
        p.className = "offcap";
        p.textContent = caption;
        sec.append(p);
      }
      sec.append(ul);
      return sec;
    };
    const ok = section("offline-ok", S.offline_ok, cards.filter((_, i) => stored[i]));
    const no = section("offline-no", S.offline_no, cards.filter((_, i) => !stored[i]), S.offline_back);
    apps.querySelectorAll(pageSections).forEach((s) => s.remove());
    apps.prepend(...[ok, no].filter(Boolean));
  }
  if (offline()) enterOffline().catch((e) => console.error(e));
  addEventListener("offline", goOffline);
  addEventListener("online", () => { if (offline()) refresh(); });
  setInterval(() => { if (offline() && !document.hidden) refresh(); }, 5000);
  for (const ev of ["touchstart", "touchend", "touchcancel"]) {
    document.addEventListener(ev, (e) => {
      touching = e.touches.length;
      if (!touching && offline()) document.dispatchEvent(new Event("hub:idle"));
    }, { capture: true, passive: true });
  }

  // The viewer's time zone decides "today" for the card lines; tell the hub when it differs. The page was just
  // drawn, so the refresh that follows doesn't blink.
  let tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { /* no Intl: keep the stored zone */ }
  if (tz && tz !== S.tz) {
    post("/api/prefs/tz", { tz }).then(() => { S.tz = tz; return refresh({ after: true, quiet: true }); }, () => {});
  }

  document.addEventListener("animationend", (e) => {
    if (e.animationName === "blink") e.target.closest(".app")?.classList.remove("blink");
  });

  // ------------------------------------------------------------ the copy on the phone (static/sw.js)
  // The hub's service worker keeps this page and the apps marked «Works offline». Unless this is that copy, tell it
  // who is logged in, which apps those are, and the hub's files this page uses (it did not see them load on the first
  // visit). The worker is the one register() gives, once active (not navigator.serviceWorker.ready, which may be an
  // app's own). Without service workers the page works as before.
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
    const user = document.querySelector(".topbar .who")?.textContent.trim();
    const worker = sw ? hubWorker(sw) : null;
    worker?.catch(() => {});
    if (worker && user && root.dataset.hubOffline !== "1") {
      const assets = [...document.querySelectorAll("link[rel=stylesheet], link[rel=manifest], script[src], img[src]")]
        .map((el) => el.href || el.src).filter((u) => u && u.startsWith(location.origin + "/"));
      worker.then((w) => w?.postMessage({ type: "hub:home", user, offline: S.offline_apps || [], assets })).catch(() => {});
    }
  } catch { /* no service workers here */ }

  // ------------------------------------------------------------ pinning
  function setPinned(li, on) {
    li.dataset.pinned = String(on);
    const b = li.querySelector(".pin");
    if (!b) return;
    b.textContent = on ? "★" : "☆";
    b.setAttribute("aria-pressed", String(on));
    b.setAttribute("aria-label", (on ? S.unpin : S.pin) + ": " + (li.querySelector("h2")?.textContent || ""));
  }
  // The star flips at once; the refresh then moves the card into or out of Favourites
  function togglePin(li) {
    const on = li.dataset.pinned !== "true";
    setPinned(li, on);
    post("/api/prefs/pin", { slug: li.dataset.slug, pinned: on }).then(
      () => refresh({ after: true }),
      () => { setPinned(li, !on); failed(); },
    );
  }

  let timer = null, swallow = null; // swallow: the card whose next click a long press ate
  function closeMenu() {
    if (!menu) return;
    menu.remove();
    menu = null;
    document.dispatchEvent(new Event("hub:idle"));
  }
  function openMenu(li, x, y) {
    if (offline()) return;
    if (menu) menu.remove();
    menu = document.createElement("div");
    menu.className = "pinmenu";
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = li.dataset.pinned === "true" ? S.unpin : S.pin;
    b.onclick = () => { closeMenu(); togglePin(li); };
    menu.append(b);
    document.body.append(menu);
    const w = menu.offsetWidth, hgt = menu.offsetHeight;
    menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, x - w / 2)) + "px";
    menu.style.top = Math.max(8, Math.min(innerHeight - hgt - 8, y + 8)) + "px";
  }
  // A finger or a button going down anywhere else closes the menu (not only a click), so an open menu never holds
  // back the refresh of a pull that starts outside it
  const outside = (e) => { if (menu && !menu.contains(e.target)) closeMenu(); };
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("touchstart", outside, { capture: true, passive: true });
  // drag.js owns the long press on favourites and asks for the menu when one was let go without moving
  document.addEventListener("hub:menu", (e) => {
    const d = e.detail || {};
    if (!d.li) return;
    swallow = d.li;
    openMenu(d.li, d.x, d.y);
  });

  // Icon view: right-click anywhere, long press outside Favourites
  document.addEventListener("contextmenu", (e) => {
    const li = at(e, ".grid .app");
    if (!li) return;
    e.preventDefault();
    if (!offline() && !root.dataset.hubDrag) openMenu(li, e.clientX, e.clientY);
  });
  document.addEventListener("touchstart", (e) => {
    swallow = null; // a long press sends no click, so clear it before the next tap
    clearTimeout(timer);
    const li = at(e, ".grid .app");
    if (!li || li.closest("#fav") || offline() || e.touches.length !== 1) return;
    const t = e.touches[0];
    timer = setTimeout(() => { swallow = li; openMenu(li, t.clientX, t.clientY); }, 500);
  }, { passive: true });
  for (const ev of ["touchend", "touchmove", "touchcancel"]) {
    document.addEventListener(ev, () => clearTimeout(timer), { passive: true });
  }
  document.addEventListener("click", (e) => {
    const eat = swallow && swallow.contains(e.target);
    swallow = null;
    if (eat) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  document.addEventListener("click", (e) => {
    if (menu && !menu.contains(e.target)) closeMenu();
    if (offline()) { // nothing saves offline; a grey card says why it does not open
      const grey = at(e, "#offline-no .app a");
      if (grey) {
        e.preventDefault();
        showToast(S.needs_net.replace("{app}", grey.closest(".app").querySelector("h2")?.textContent || ""));
      }
      return;
    }
    const fold = at(e, ".gtoggle, .gclosed");
    if (fold) {
      e.preventDefault();
      if (!window.hubDragJustEnded?.()) toggleGroup(fold.closest("section.group"));
      return;
    }
    const pin = at(e, ".pin");
    if (pin) {
      e.preventDefault();
      togglePin(pin.closest(".app"));
      return;
    }
    const v = at(e, "[data-set-view]");
    if (v && v.getAttribute("aria-pressed") !== "true") {
      const was = document.querySelector('[data-set-view][aria-pressed="true"]')?.dataset.setView;
      pressView(v.dataset.setView);
      post("/api/prefs/view", { view: v.dataset.setView }).then(
        () => refresh({ after: true }),
        () => { pressView(was); failed(); },
      );
      return;
    }
    if (at(e, "[data-open-picker]")) openPicker();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  addEventListener("scroll", closeMenu, { passive: true });

  // ------------------------------------------------------------ "Choose apps"
  // Each tick is saved at once; closing the list refreshes the page if anything changed
  let changed = false, seenSent = false;
  const saving = new Set();
  const track = (p) => { saving.add(p); p.finally(() => saving.delete(p)); };
  function openPicker() {
    picker.showModal();
    // The page lives on, so tell the hub again whenever the list shows apps marked new
    const hadNew = !!picker.querySelector(".new");
    if (!seenSent || hadNew) {
      seenSent = true;
      track(post("/api/prefs/seen", {}).then(() => { if (hadNew) changed = true; }, () => {}));
    }
  }
  document.addEventListener("change", (e) => {
    const cb = at(e, "#picker input[type=checkbox]");
    if (!cb) return;
    track(post("/api/prefs/apps", { slug: cb.dataset.slug, added: cb.checked }).then(
      () => { changed = true; },
      () => { cb.checked = !cb.checked; failed(); },
    ));
  });
  // The dialog itself and its footer are never swapped, only the list inside
  picker.querySelector("[data-close]").addEventListener("click", () => picker.close());
  picker.addEventListener("click", (e) => { if (e.target === picker) picker.close(); }); // the backdrop
  picker.addEventListener("close", () => {
    document.dispatchEvent(new Event("hub:idle"));
    Promise.all(saving).then(() => {
      if (!changed) return;
      changed = false;
      refresh({ after: true });
    });
  });
})();
