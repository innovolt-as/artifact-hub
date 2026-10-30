/*
 * pull.js — pull to refresh, on the hub's own pages and injected into every app page (next to hub.js).
 *
 * Only when the hub runs as a home-screen app: iOS has no pull to refresh there, while a browser tab has its own.
 * It works like other iPhone apps. The bar on top stays still: the front page's .topbar, or the app banner
 * (hub-banner, which sits outside <body>). Only the content under it ([data-pull-content], or <body> in an app)
 * follows the finger, with rubber-band resistance, and a ring sits in the gap that opens. Letting go before ARM
 * slides the content back. Letting go after ARM holds it open while the ring spins, and then
 *   - on the front page (window.hubRefresh from home.js) refreshes in place, slides back and glows the top bar
 *     green, or red when the refresh failed;
 *   - elsewhere reloads the page, and the new page glows the banner once (sessionStorage "hub-pull-glow").
 * While our pull is under way, touchmove prevents the default so iOS's own rubber band at the top doesn't run as
 * well. Only transform and opacity change per frame. The transform is removed again once the content is back, so
 * position: fixed in the apps works as before (while the content moves, fixed elements in an app move with it).
 *
 * Starts only with the page scrolled to the very top, not while typing in a field, not on something fixed
 * (sheets, menus, tab bars), not inside a scroll area that is not at its top, not with two fingers, and not while a
 * favourite is being dragged (<html data-hub-drag>, set by drag.js; setting it mid-pull cancels the pull).
 */
(function () {
  if (window.__hubPull) return;
  window.__hubPull = true;
  if (!(navigator.standalone === true || matchMedia("(display-mode: standalone)").matches)) return;

  const ARM = 120;  // px of finger travel before letting go refreshes (80 was too easy to set off)
  const HOLD = 56;  // px the content stays open while the ring spins
  const SLIDE = "transform .28s cubic-bezier(.2,.8,.2,1)";
  const SPIN = 500;  // ms the ring spins at least, so a quick refresh still reads as one
  const GLOW = 900;  // ms, as the glow animations in hub.css and in the banner's style
  const FLAG = "hub-pull-glow";
  const rubber = (d) => 140 * (1 - Math.exp(-d / 220));  // gives less and less, never past 140 px
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const root = document.documentElement;
  const content = () => document.querySelector("[data-pull-content]") || document.body;

  // What stays still above the content: the app banner once it is out of <body>, or the front page's top bar
  function header(el) {
    for (const h of [document.querySelector("hub-banner"), document.querySelector(".topbar")]) {
      if (h && !el.contains(h)) return h;
    }
    return null;
  }

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

  let glowTimer = 0;
  function glow(bar, ok) {
    if (!bar) return;
    const banner = bar.localName === "hub-banner";
    const off = () => (banner ? bar.removeAttribute("data-glow") : bar.classList.remove("glow-ok", "glow-fail"));
    clearTimeout(glowTimer);
    if (banner ? bar.hasAttribute("data-glow") : /glow-/.test(bar.className)) {
      off();
      void bar.offsetWidth;  // still glowing from the last one: restart the animation
    }
    if (banner) bar.setAttribute("data-glow", ok ? "ok" : "fail");
    else bar.classList.add(ok ? "glow-ok" : "glow-fail");
    glowTimer = setTimeout(off, GLOW);
  }

  // Back after a pull in an app (or on a page without hubRefresh) reloaded it
  try {
    if (sessionStorage.getItem(FLAG)) {
      sessionStorage.removeItem(FLAG);
      glow(header(content()), true);
    }
  } catch (e) { /* no sessionStorage: no glow */ }

  // ------------------------------------------------------------------ the ring
  const ARROW = "M12 5v14M6 13l6 6 6-6", ARC = "M21 12a9 9 0 1 1-2.6-6.4";
  let host = null, ring = null, path = null;
  function indicator() {
    if (host) return;
    host = document.createElement("hub-pull");
    const sr = host.attachShadow({ mode: "open" });
    sr.innerHTML =
      "<style>" +
      ".ring{width:36px;height:36px;border-radius:50%;background:#fff;color:#123566;display:grid;place-items:center;" +
      "box-shadow:0 2px 10px rgb(0 0 0 / .25)}" +
      "svg{width:20px;height:20px;transition:transform .15s}.armed svg{transform:rotate(180deg)}" +
      ".spin svg{animation:s .8s linear infinite}@keyframes s{to{transform:rotate(360deg)}}" +
      "</style><div class=ring><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' " +
      "stroke-linecap='round' stroke-linejoin='round'><path/></svg></div>";
    ring = sr.querySelector(".ring");
    path = sr.querySelector("path");
    root.append(host);  // on <html>, not in what moves
  }

  // ------------------------------------------------------------------ the content
  let state = "";  // "" at rest, "pull" following the finger, "back" sliding back, "busy" held open
  let el = null, bar = null, saved = null, y = 0, timer = 0, gen = 0;

  // The first move down: remember the content's own inline styles and put the ring under the bar
  function begin() {
    el = content();
    bar = header(el);
    saved = { attr: el.hasAttribute("style"), props: ["transform", "transition"].map((p) =>
      [p, el.style.getPropertyValue(p), el.style.getPropertyPriority(p)]) };
    indicator();
    const below = bar ? Math.max(0, bar.getBoundingClientRect().bottom) : 0;
    // z-index under the bar (20), so the ring comes out from under it; the moving content is a stacking context
    host.setAttribute("style",
      "all:initial;position:fixed;left:50%;z-index:19;pointer-events:none;display:block;opacity:0;" +
      `top:${below ? below + "px" : "env(safe-area-inset-top)"}`);
    ring.className = "ring";
    path.setAttribute("d", ARROW);
    state = "pull";
  }

  // Content at `to` px down and the ring in the middle of the gap, or while the gap is smaller than HOLD just above
  // the content's edge, coming out from under the bar; `slide` animates there, otherwise it is immediate
  function move(to, slide) {
    y = to;
    el.style.setProperty("transition", slide ? SLIDE : "none", "important");
    el.style.setProperty("transform", `translate3d(0,${to}px,0)`, "important");
    host.style.transition = slide ? SLIDE + ",opacity .28s" : "none";
    host.style.transform = `translate(-50%,${Math.min(to / 2, to - HOLD / 2) - 18}px)`;
  }

  function follow(d) {
    move(rubber(d), false);
    host.style.opacity = String(Math.min(1, d / ARM));
    ring.classList.toggle("armed", d >= ARM);
  }

  function back() {
    state = "back";
    const was = y;
    move(0, true);
    host.style.opacity = "0";
    clearTimeout(timer);
    // transitionend finishes it; nothing slides from 0, and a hidden page may never send it
    timer = setTimeout(rest, was ? 400 : 0);
  }

  // Back at rest: the transform goes away entirely, so position: fixed in the apps is relative to the screen again
  function rest() {
    clearTimeout(timer);
    if (el) {
      for (const [p, v, prio] of saved.props) {
        if (v) el.style.setProperty(p, v, prio);
        else el.style.removeProperty(p);
      }
      if (!saved.attr && !el.getAttribute("style")) el.removeAttribute("style");
    }
    if (host) host.style.display = "none";
    el = bar = saved = null;
    y = 0;
    state = "";
    gen++;
  }

  addEventListener("transitionend", (e) => {
    if (state === "back" && e.target === el && e.propertyName === "transform") rest();
  });

  async function hold() {
    state = "busy";
    const me = ++gen;
    ring.classList.remove("armed");
    ring.classList.add("spin");
    path.setAttribute("d", ARC);
    host.style.opacity = "1";
    move(HOLD, true);
    const refresh = window.hubRefresh;  // home.js loads after this file, so look it up now
    if (typeof refresh !== "function") {
      try { sessionStorage.setItem(FLAG, "1"); } catch (e) { /* no glow then */ }
      location.reload();
      return;
    }
    const ok = await Promise.race([
      Promise.all([Promise.resolve().then(() => refresh()).catch(() => false), sleep(SPIN)]).then(([r]) => r === true),
      sleep(15000).then(() => false),  // a fetch that hangs must not hold the page open for ever
    ]);
    if (me !== gen) return;  // reset meanwhile (back from the page cache)
    glow(bar, ok);
    back();
  }

  // ------------------------------------------------------------------ the finger
  // While startY is set (a finger that may pull), state is "" or "pull"; "pull" means the finger is below its start
  let startY = null, startX = 0, dist = 0, from = null;

  function stop() {
    startY = null;
    if (state === "pull") back();
  }

  addEventListener("touchstart", (e) => {
    if (state === "pull") return stop();  // a second finger
    startY = null;
    if (state || e.touches.length !== 1 || root.dataset.hubDrag || blocked(e.target)) return;
    startY = e.touches[0].clientY;
    startX = e.touches[0].clientX;
    from = e.target;
    dist = 0;
  }, { passive: true });

  addEventListener("touchmove", (e) => {
    if (startY === null) return;
    if (e.touches.length !== 1 || root.dataset.hubDrag) return stop();
    const t = e.touches[0];
    dist = t.clientY - startY;
    if (dist <= 0) {  // back above the start: the content is at 0 anyway, and the page may scroll the usual way
      if (state === "pull") rest();
      return;
    }
    if (state !== "pull") {
      // Not for a swipe that is more sideways than down (a carousel, say), not once the page has taken the gesture
      // as its own scroll (we could not stop its rubber band any more), and not if it scrolled since touchstart
      if (Math.abs(t.clientX - startX) > dist || !e.cancelable || blocked(from)) {
        startY = null;
        return;
      }
      begin();
    }
    if (e.cancelable) e.preventDefault();  // keeps iOS's own rubber band out of our pull
    follow(dist);
  }, { passive: false });

  addEventListener("touchend", () => {
    if (startY === null) return;
    startY = null;
    if (state !== "pull") return;
    if (dist >= ARM) hold();
    else back();
  }, { passive: true });

  addEventListener("touchcancel", stop, { passive: true });

  // A favourite lifted while the finger is still (drag.js): no touchmove comes to notice it
  new MutationObserver(() => { if (root.dataset.hubDrag) stop(); })
    .observe(root, { attributes: true, attributeFilter: ["data-hub-drag"] });

  // Hidden mid-pull (app switcher, lock): nothing will finish the slide, so go straight to rest
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) return;
    startY = null;
    if (state === "pull" || state === "back") rest();
  });
  // Back from the page cache with the content still held open
  addEventListener("pageshow", (e) => { if (e.persisted && state) rest(); });
})();
