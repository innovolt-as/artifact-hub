/*
 * drag.js — hold and drag to reorder the favourites on the front page (#fav), with a finger or a mouse.
 *
 * Holding a favourite still for HOLD ms lifts it (.lifted in hub.css: a little larger, with a shadow). It then
 * follows the pointer, and the other favourites slide aside (.sliding) to show where it will land: the slot whose
 * centre is nearest the pointer. Letting go saves the whole order at once (POST /api/prefs/pins, with keepalive, so
 * opening an app right after the drop doesn't lose it), glides the favourite there and moves the node in the DOM.
 * If saving fails, the favourites glide back once it has landed and the usual alert shows. Letting go without
 * having moved opens the pin/unpin menu in the icon view (hub:menu, handled by home.js) and does nothing in the
 * list view, where the star is. A short tap still opens the app, and moving more than SLOP px before the hold is up
 * is a scroll, not a drag. The right mouse button keeps its own menu (home.js).
 *
 * From the lift until the favourite has landed, <html data-hub-drag="1"> is set: home.js holds back a refresh (it
 * would swap the cards under the finger), pull.js doesn't pull, and a non-passive touchmove listener keeps the
 * page from scrolling. Every lift ends in end(), exactly once, which clears the flag and sends "hub:idle" (home.js
 * waits for it with no timeout). A drop leads there, and so does a cancel (pointercancel, lost capture, the page
 * hidden or left); both still get there if something in them throws. The click that follows a lift is swallowed,
 * so letting go never opens the app.
 *
 * The slots are measured once, at the lift. Moving only writes transforms.
 */
(function () {
  const HOLD = 450;   // ms a press must stay still to lift
  const SLOP = 8;     // px the pointer may move before that; more is a scroll
  const SETTLE = 220; // ms, the .2s transform transition of .sliding in hub.css and a little more
  const root = document.documentElement;
  const at = (e, sel) => (e.target instanceof Element ? e.target.closest(sel) : null);
  const translate = (x, y) => (x || y ? `translate(${x}px, ${y}px)` : "");

  let press = null;  // a pointer held on a favourite, not lifted yet
  let drag = null;   // the lifted favourite, until it has landed
  let swallow = 0;   // a click before this time is the one that follows a lift
  let saves = 0;     // number of the latest save

  const still = (e) => {
    if (root.dataset.hubDrag && e.cancelable) e.preventDefault();
  };

  function cancelPress() {
    if (!press) return;
    clearTimeout(press.timer);
    press = null;
  }

  // ------------------------------------------------------------------ lift
  function lift() {
    const p = press;
    press = null;
    // A refresh may have swapped the card since the press: find it again, and only in Favourites
    const li = [...document.querySelectorAll("#fav .app")].find((n) => n.dataset.slug === p.slug);
    if (!li) return;
    try {
      li.setPointerCapture(p.id);
    } catch {
      return; // the pointer is no longer down
    }
    const ul = li.parentElement;
    const items = [...ul.children].filter((n) => n.matches(".app"));
    const sx = scrollX, sy = scrollY;
    const slots = items.map((n) => {
      const r = n.getBoundingClientRect();
      return { x: r.left + sx, y: r.top + sy, w: r.width, h: r.height };
    });
    li.classList.add("lifted");
    for (const n of items) if (n !== li) n.classList.add("sliding");
    getSelection()?.removeAllRanges();
    // A finger's touch events keep going to the node it first touched, even after a refresh took that node out
    // of the page; then they never reach the listener on document, and the page would scroll
    p.target.addEventListener("touchmove", still, { passive: false });
    const from = items.indexOf(li);
    drag = {
      id: p.id, li, ul, items, slots, from, to: from, touched: p.target,
      // One column (the list view on a phone): cards can differ in height, so the others are stacked, not put
      // into each other's slots
      column: slots.every((s) => Math.abs(s.x - slots[0].x) < 1),
      gap: slots.length > 1 ? slots[1].y - slots[0].y - slots[0].h : 0,
      x0: p.x + sx, y0: p.y + sy, // the pointer at the lift, in page coordinates
      x: p.x, y: p.y, sx, sy,     // the pointer now (viewport) and the scroll now
      moved: false, done: false,
    };
    root.dataset.hubDrag = "1"; // last, so a lift that got this far always has a drag that will clear it
  }

  // ------------------------------------------------------------------ move
  // The favourites in the order they would have if dropped now
  function order(d) {
    const o = d.items.filter((n) => n !== d.li);
    o.splice(d.to, 0, d.li);
    return o;
  }
  // Where each favourite's top left corner goes in that order, in page coordinates
  function places(d, o) {
    const out = new Map();
    let y = d.slots[0].y;
    o.forEach((n, j) => {
      if (d.column) {
        out.set(n, { x: d.slots[0].x, y });
        y += d.slots[d.items.indexOf(n)].h + d.gap;
      } else {
        out.set(n, { x: d.slots[j].x, y: d.slots[j].y });
      }
    });
    return out;
  }
  const offset = (d, n, p) => {
    const s = d.slots[d.items.indexOf(n)];
    return translate(p.x - s.x, p.y - s.y);
  };

  function move(x, y) {
    const d = drag;
    d.x = x;
    d.y = y;
    // Page coordinates: when the page scrolls under a still pointer (a mouse wheel, say), the card stays under the
    // pointer and so moves on the page, which counts as moving it
    const px = x + d.sx, py = y + d.sy;
    if (!d.moved && Math.hypot(px - d.x0, py - d.y0) > SLOP) d.moved = true;
    d.li.style.transform = translate(px - d.x0, py - d.y0);
    let to = d.to, best = Infinity;
    d.slots.forEach((s, i) => {
      const dist = Math.hypot(s.x + s.w / 2 - px, s.y + s.h / 2 - py);
      if (dist < best) { best = dist; to = i; }
    });
    if (to === d.to) return;
    d.to = to;
    const p = places(d, order(d));
    for (const n of d.items) if (n !== d.li) n.style.transform = offset(d, n, p.get(n));
  }

  // ------------------------------------------------------------------ land
  // Always the last step of a lift: drag styles off at once, flag cleared, waiting refreshes told
  function end(d) {
    try {
      for (const n of d.items) {
        n.classList.remove("lifted", "sliding");
        n.style.transform = "";
      }
      d.touched.removeEventListener("touchmove", still);
    } finally {
      if (drag === d) drag = null;
      delete root.dataset.hubDrag;
      document.dispatchEvent(new Event("hub:idle"));
    }
  }
  // Let the glide that was just started play, then run `then` and end the lift whatever happens
  function settle(d, then) {
    d.done = true;
    setTimeout(() => {
      try {
        then();
      } finally {
        end(d);
      }
    }, SETTLE);
  }

  function drop(d) {
    swallow = performance.now() + 1000;
    d.done = true; // no second drop or cancel for this lift; end() follows exactly once, below or after the glide
    if (!d.moved) {
      // A long press. The menu opens before the flag is cleared, so a refresh waiting for hub:idle sees it open.
      try {
        if (d.ul.classList.contains("grid")) {
          document.dispatchEvent(new CustomEvent("hub:menu", { detail: { li: d.li, x: d.x, y: d.y } }));
        }
      } finally {
        end(d);
      }
      return;
    }
    try {
      const o = order(d);
      const before = d.items.map((n) => n.dataset.slug);
      const n = d.to === d.from ? 0 : ++saves;
      const sent = n ? save(o.map((x) => x.dataset.slug)) : null; // now, not after the glide
      d.li.classList.add("sliding");
      d.li.style.transform = offset(d, d.li, places(d, o).get(d.li));
      settle(d, () => {
        if (!sent) return;
        for (const x of o) d.ul.append(x); // end() then takes the transforms off in the same frame: nothing jumps
        sent.then((ok) => { if (!ok) unsaved(n, before); }); // runs after end(), once this lift is over
      });
    } catch (e) {
      end(d); // the glide was never set up, so nothing else will land it
      throw e;
    }
  }

  function cancel(d) {
    swallow = performance.now() + 1000;
    d.done = true;
    try {
      for (const n of d.items) {
        n.classList.add("sliding");
        n.style.transform = "";
      }
    } finally {
      settle(d, () => {}); // glide back, then end()
    }
  }

  // ------------------------------------------------------------------ save
  // The whole order; resolves to whether the hub kept it. keepalive: the request still goes out when an app is
  // opened right after the drop.
  function save(slugs) {
    return fetch("/api/prefs/pins", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order: slugs }),
    }).then((r) => r.ok, () => false);
  }

  // Save number n failed, and its favourite has landed
  function unsaved(n, before) {
    // A later save sends the whole order again, and a favourite held right now, or pressed and about to lift, must
    // not move under the finger
    if (n === saves && !drag && !press) restore(before);
    setTimeout(() => alert(JSON.parse(document.getElementById("__hub_strings").textContent).save_failed), SETTLE);
  }

  // Back to the order before the drop, gliding. Found by slug: a refresh may have swapped the cards meanwhile.
  function restore(slugs) {
    const ul = document.querySelector("#fav ul");
    if (!ul) return;
    const items = [...ul.children].filter((n) => n.matches(".app"));
    const rank = (n) => (slugs.includes(n.dataset.slug) ? slugs.indexOf(n.dataset.slug) : slugs.length);
    const want = [...items].sort((a, b) => rank(a) - rank(b));
    if (want.every((n, i) => n === items[i])) return;
    const was = new Map(items.map((n) => [n, n.getBoundingClientRect()]));
    for (const n of want) ul.append(n);
    for (const n of items) {
      const a = was.get(n), b = n.getBoundingClientRect();
      n.style.transform = translate(a.left - b.left, a.top - b.top);
    }
    void ul.offsetWidth; // start from where they were...
    for (const n of items) {
      n.classList.add("sliding");
      n.style.transform = ""; // ...and slide to where they are now
    }
    setTimeout(() => { if (!drag) for (const n of items) n.classList.remove("sliding"); }, SETTLE);
  }

  // ------------------------------------------------------------------ listeners
  document.addEventListener("pointerdown", (e) => {
    swallow = 0;
    cancelPress(); // a second finger: no lift
    if (drag || !e.isPrimary || e.button !== 0) return; // the right button is for the menu
    const li = at(e, "#fav .app");
    if (!li) return;
    press = {
      id: e.pointerId, slug: li.dataset.slug, mouse: e.pointerType === "mouse", target: e.target,
      x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, timer: setTimeout(lift, HOLD),
    };
  });
  document.addEventListener("pointermove", (e) => {
    if (press && e.pointerId === press.id) {
      if (Math.hypot(e.clientX - press.x0, e.clientY - press.y0) > SLOP) return cancelPress();
      press.x = e.clientX;
      press.y = e.clientY;
    } else if (drag && !drag.done && e.pointerId === drag.id) {
      if (e.pointerType === "mouse" && !(e.buttons & 1)) return cancel(drag); // the button came up unseen
      move(e.clientX, e.clientY);
    }
  });
  document.addEventListener("pointerup", (e) => {
    if (press && e.pointerId === press.id) cancelPress();
    else if (drag && !drag.done && e.pointerId === drag.id) drop(drag);
  });
  document.addEventListener("pointercancel", (e) => {
    if (press && e.pointerId === press.id) cancelPress();
    else if (drag && !drag.done && e.pointerId === drag.id) cancel(drag);
  });
  // Also sent when a touch's own capture moves to the lifted card; only losing the card's capture cancels
  document.addEventListener("lostpointercapture", (e) => {
    if (drag && !drag.done && e.pointerId === drag.id && (e.target === drag.li || !drag.li.isConnected)) cancel(drag);
  });
  const away = () => {
    cancelPress();
    if (drag && !drag.done) cancel(drag);
  };
  document.addEventListener("visibilitychange", () => { if (document.hidden) away(); });
  addEventListener("blur", away);
  addEventListener("scroll", () => {
    if (!drag || drag.done) return;
    drag.sx = scrollX;
    drag.sy = scrollY;
    move(drag.x, drag.y); // the page moved under a still pointer: keep the card under it
  }, { passive: true });

  // The page stays still while a favourite is lifted
  document.addEventListener("touchmove", still, { passive: false });
  document.addEventListener("click", (e) => {
    if (performance.now() >= swallow) return;
    swallow = 0;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  // No native link drag with the mouse, and no system menu (Android's long press) while a finger holds a favourite
  document.addEventListener("dragstart", (e) => { if (at(e, "#fav")) e.preventDefault(); });
  document.addEventListener("contextmenu", (e) => {
    if (!drag && !(press && !press.mouse)) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
})();
