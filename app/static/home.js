// Front page: greeting and date from the viewer's clock, view toggle, pinning (star in the card view,
// long-press / right-click menu in the icon view). Prefs live on the account (/api/prefs/*).
(function () {
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
  const failed = () => alert("Kunne ikke lagre. Prøv igjen.");

  const now = new Date(), h = now.getHours();
  document.getElementById("hello").textContent =
    h < 5 ? "God natt" : h < 10 ? "God morgen" : h < 12 ? "God formiddag" : h < 18 ? "God ettermiddag" : "God kveld";
  document.getElementById("today").textContent =
    now.toLocaleDateString("no-NO", { weekday: "long", day: "numeric", month: "long" });

  document.querySelectorAll("[data-set-view]").forEach((b) => {
    b.onclick = () => {
      if (b.getAttribute("aria-pressed") === "true") return;
      post("/api/prefs/view", { view: b.dataset.setView }).then(() => location.reload(), failed);
    };
  });

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
    b.textContent = li.dataset.pinned === "true" ? "Fjern fra favoritter" : "Legg til i favoritter";
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
