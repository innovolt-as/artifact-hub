// Front page: greeting and date from the viewer's clock, view toggle, pinning (star in the card view,
// long-press / right-click menu in the icon view) and the "Velg apper" list. Prefs live on the account
// (/api/prefs/*). The page never reloads: it fetches itself again, swaps in what changed and blinks those cards.
//
// Shared with pull.js and drag.js:
//   window.hubRefresh() -> Promise<boolean>  true when the page was updated, false when fetching it failed
//   "hub:menu" on document, detail {li, x, y} opens the pin/unpin menu (drag.js: long press on a favourite)
//   "hub:idle" on document                    a drag or the menu is done, so a waiting refresh may run
//   <html data-hub-drag="1">                  set by drag.js while a favourite is being dragged
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

  // ------------------------------------------------------------ refresh in place
  const keyOf = (li) => (li.closest("section")?.id || "") + "/" + li.dataset.slug;
  const cardsOf = (home) => new Map([...home.querySelectorAll("li.app[data-slug]")].map((li) => [keyOf(li), li]));
  // What the server drew: each card's HTML by section/slug, and the rest of #home with the cards as placeholders
  // (sections, slug order, the dot on "Velg apper"...). Taken from server markup only, never from the live page,
  // so classes like blink or a drag's inline styles don't count as changes.
  function snapshot(home) {
    const frame = home.cloneNode(true);
    frame.querySelectorAll("li.app[data-slug]").forEach((li) => li.replaceWith("[" + li.dataset.slug + "]"));
    return {
      cards: new Map([...cardsOf(home)].map(([k, li]) => [k, li.outerHTML])),
      frame: frame.outerHTML,
      view: home.querySelector(".apps")?.dataset.view,
    };
  }
  let shown = snapshot(document.getElementById("home"));

  const pressView = (view) =>
    document.querySelectorAll("[data-set-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setView === view)));

  function apply(doc, quiet) {
    const fresh = doc.getElementById("home");
    const next = snapshot(fresh);
    const redrawn = [...cardsOf(fresh)].filter(([k]) => shown.cards.get(k) !== next.cards.get(k)); // new here or changed
    let home = document.getElementById("home");
    const live = cardsOf(home);
    const focused = document.activeElement;
    const focusLi = focused && home.contains(focused) ? focused.closest("li.app") : null;
    let swapped;
    if (next.frame === shown.frame && redrawn.every(([k]) => live.has(k))) {
      swapped = redrawn.map(([k, li]) => { // same layout: only the changed cards
        const n = document.importNode(li, true);
        live.get(k).replaceWith(n);
        return n;
      });
    } else {
      const n = document.importNode(fresh, true);
      home.replaceWith(n);
      home = n;
      const now = cardsOf(n);
      swapped = redrawn.map(([k]) => now.get(k));
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

  // Wait while a favourite is dragged, the pin menu is open or "Velg apper" is open; each of them sends hub:idle
  const busy = () => !!(root.dataset.hubDrag || menu || picker.open);
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
    let doc;
    try {
      const r = await fetch("/", { credentials: "same-origin", cache: "no-store" });
      if (r.status !== 200) return false;
      doc = new DOMParser().parseFromString(await r.text(), "text/html");
    } catch {
      return false;
    }
    if (!doc.getElementById("home")) return false; // e.g. the login page after the session ran out
    do { await idle(); } while (busy()); // don't move cards under a finger: something may have started while fetching
    try {
      apply(doc, quiet);
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

  // Back on the page: from another tab or app, or from the browser's back/forward cache
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  addEventListener("pageshow", (e) => { if (e.persisted) refresh(); });

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
    if (!root.dataset.hubDrag) openMenu(li, e.clientX, e.clientY);
  });
  document.addEventListener("touchstart", (e) => {
    swallow = null; // a long press sends no click, so clear it before the next tap
    clearTimeout(timer);
    const li = at(e, ".grid .app");
    if (!li || li.closest("#fav") || e.touches.length !== 1) return;
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

  // ------------------------------------------------------------ "Velg apper"
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
