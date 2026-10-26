// Front page: greeting and date from the viewer's clock, view toggle, pinning (star in the card view,
// long-press / right-click menu in the icon view), the "Velg apper" list, and a fresh page when coming back
// after a while. Prefs live on the account (/api/prefs/*).
(function () {
  const STALE_MS = 5 * 60 * 1000; // back after longer than this (e.g. the home-screen app resumed) -> reload
  let hiddenAt = null;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (hiddenAt !== null && Date.now() - hiddenAt > STALE_MS) location.reload();
  });

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
  const S = JSON.parse(document.getElementById("__hub_strings").textContent);
  const failed = () => alert(S.save_failed);

  const now = new Date(), h = now.getHours();
  document.getElementById("hello").textContent =
    S.greet[h < 5 ? 0 : h < 10 ? 1 : h < 12 ? 2 : h < 18 ? 3 : 4];
  document.getElementById("today").textContent =
    now.toLocaleDateString(S.locale, { weekday: "long", day: "numeric", month: "long" });

  document.querySelectorAll("[data-set-view]").forEach((b) => {
    b.onclick = () => {
      if (b.getAttribute("aria-pressed") === "true") return;
      post("/api/prefs/view", { view: b.dataset.setView }).then(() => location.reload(), failed);
    };
  });

  // "Velg apper": each tick is saved at once; closing the list reloads the page if anything changed
  const picker = document.getElementById("picker");
  let changed = false, seenSent = false;
  document.querySelectorAll("[data-open-picker]").forEach((b) => {
    b.onclick = () => {
      picker.showModal();
      if (!seenSent) {
        seenSent = true;
        post("/api/prefs/seen", {}).catch(() => {});
      }
    };
  });
  picker.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.onchange = () =>
      post("/api/prefs/apps", { slug: cb.dataset.slug, added: cb.checked }).then(
        () => { changed = true; },
        () => { cb.checked = !cb.checked; failed(); },
      );
  });
  picker.querySelector("[data-close]").onclick = () => picker.close();
  picker.addEventListener("click", (e) => { if (e.target === picker) picker.close(); }); // the backdrop
  picker.addEventListener("close", () => { if (changed) location.reload(); });

  const togglePin = (li) =>
    post("/api/prefs/pin", { slug: li.dataset.slug, pinned: li.dataset.pinned !== "true" }).then(() => location.reload(), failed);

  document.querySelectorAll(".pin").forEach((b) => {
    b.onclick = (e) => {
      e.preventDefault();
      togglePin(b.closest(".app"));
    };
  });

  let menu = null, timer = null, swallowClick = false;
  const closeMenu = () => { if (menu) { menu.remove(); menu = null; } };
  function openMenu(li, x, y) {
    closeMenu();
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
  document.querySelectorAll(".grid .app").forEach((li) => {
    li.addEventListener("contextmenu", (e) => { e.preventDefault(); openMenu(li, e.clientX, e.clientY); });
    li.addEventListener("touchstart", (e) => {
      const t = e.touches[0];
      swallowClick = false; // a long press sends no click, so clear it before the next tap
      clearTimeout(timer);
      timer = setTimeout(() => { swallowClick = true; openMenu(li, t.clientX, t.clientY); }, 500);
    }, { passive: true });
    for (const ev of ["touchend", "touchmove", "touchcancel"]) li.addEventListener(ev, () => clearTimeout(timer));
    li.addEventListener("click", (e) => {
      if (swallowClick) { e.preventDefault(); swallowClick = false; }
    }, true);
  });
  document.addEventListener("click", (e) => { if (menu && !menu.contains(e.target)) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  addEventListener("scroll", closeMenu, { passive: true });
})();
