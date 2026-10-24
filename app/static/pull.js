/*
 * pull.js — pull to refresh, on the hub's own pages and injected into every app page (next to hub.js).
 *
 * Only when the hub runs as a home-screen app: iOS has no pull to refresh there, while a browser tab has its own.
 * Starts only with the page scrolled to the very top, not while typing in a field, and not on something fixed
 * (sheets, menus, tab bars) or inside a scroll area that is not at its top. It never prevents scrolling; the
 * indicator just follows the finger, and letting go far enough reloads the page.
 */
(function () {
  if (window.__hubPull) return;
  window.__hubPull = true;
  if (!(navigator.standalone === true || matchMedia("(display-mode: standalone)").matches)) return;

  const ARM = 120;  // px to pull before letting go reloads (80 was too easy to set off)
  const MAX = 180;  // px after which the indicator stops following
  let startY = null, dist = 0, host = null, ring = null;

  function blocked(target) {
    if ((document.scrollingElement || document.documentElement).scrollTop > 0 || scrollY > 0) return true;
    const a = document.activeElement;
    if (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return true;
    for (let n = target; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.position === "fixed") return true;
      if (n.scrollTop > 0 && /auto|scroll/.test(cs.overflowY)) return true;
    }
    return false;
  }

  function indicator() {
    if (host) return host;
    host = document.createElement("hub-pull");
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML =
      "<style>" +
      ".ring{width:36px;height:36px;border-radius:50%;background:#fff;color:#123566;display:grid;place-items:center;" +
      "box-shadow:0 2px 10px rgb(0 0 0 / .25)}" +
      "svg{width:20px;height:20px;transition:transform .15s}.armed svg{transform:rotate(180deg)}" +
      ".spin svg{animation:s .8s linear infinite}@keyframes s{to{transform:rotate(360deg)}}" +
      "</style><div class=ring><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' " +
      "stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M6 13l6 6 6-6'/></svg></div>";
    ring = root.querySelector(".ring");
    (document.body || document.documentElement).append(host);
    return host;
  }

  function show(d) {
    const h = indicator();
    const banner = document.querySelector("hub-banner");
    const below = banner ? Math.max(0, banner.getBoundingClientRect().bottom) : 0;
    const top = below ? below + 8 + "px" : "calc(env(safe-area-inset-top) + 8px)";
    const y = (Math.min(d, MAX) / MAX) * 56 - 28;
    h.setAttribute("style",
      "all:initial;position:fixed;left:50%;z-index:2147483647;pointer-events:none;display:block;" +
      `top:${top};transform:translate(-50%,${y}px);opacity:${Math.min(1, d / ARM)}`);
    ring.classList.toggle("armed", d >= ARM);
  }

  function hide() {
    if (host) host.style.setProperty("opacity", "0");
    startY = null;
    dist = 0;
  }

  addEventListener("touchstart", (e) => {
    startY = e.touches.length === 1 && !blocked(e.target) ? e.touches[0].clientY : null;
    dist = 0;
  }, { passive: true });

  addEventListener("touchmove", (e) => {
    if (startY === null) return;
    if (e.touches.length !== 1) return hide();
    dist = e.touches[0].clientY - startY;
    if (dist > 0) show(dist);
    else if (host) host.style.setProperty("opacity", "0");
  }, { passive: true });

  addEventListener("touchend", () => {
    if (startY !== null && dist >= ARM) {
      show(ARM);
      ring.classList.remove("armed");
      ring.classList.add("spin");
      ring.querySelector("path").setAttribute("d", "M21 12a9 9 0 1 1-2.6-6.4");
      location.reload();
      return;
    }
    hide();
  }, { passive: true });

  addEventListener("touchcancel", hide, { passive: true });
})();
