/*
 * drag.js — hold and drag to reorder the front page, with a finger or a mouse: the cards in an ordered section
 * (<section data-order>: the favourites, #fav, and each group), and the groups themselves by their heading.
 *
 * Holding a card still for HOLD ms lifts it (.lifted in hub.css: a little larger, with a shadow). It then follows the
 * pointer, and the other cards of its section slide aside (.sliding) to show where it will land: the slot whose
 * centre is nearest the pointer. A card never leaves its section; moving apps between groups is done in "Choose
 * apps". Letting go saves the section's whole order at once (data-order="pins": POST /api/prefs/pins {order};
 * "group": /api/prefs/groups/apps {id, order}), with keepalive, so opening an app right after the drop doesn't lose
 * it, glides the card there and moves the node in the DOM. If saving fails, the cards glide back once it has landed
 * and the usual alert shows. Letting go without having moved opens the pin/unpin menu in the icon view (hub:menu,
 * handled by home.js) and does nothing in the list view, where the star is. A short tap still opens the app, and
 * moving more than SLOP px before the hold is up is a scroll, not a drag. The right mouse button keeps its own menu
 * (home.js).
 *
 * Holding a group's heading (.gtoggle) the same way lifts the whole group section, open or closed, as one block. It
 * moves up and down among the other groups only (Favourites and the rest stay put), and the drop saves the order of
 * the groups (/api/prefs/groups/order {order: [ids]}). Groups differ in height, so a group lands where its top is
 * nearest to where it would sit. A short tap on the heading still folds the group (home.js); the click that follows
 * a lift doesn't, and window.hubDragJustEnded() tells home.js so.
 *
 * From the lift until the card or group has landed, <html data-hub-drag="1"> is set: home.js holds back a refresh
 * (it would swap the cards under the finger), pull.js doesn't pull, and a non-passive touchmove listener keeps the
 * page from scrolling. Every lift ends in end(), exactly once, which clears the flag and sends "hub:idle" (home.js
 * waits for it with no timeout). A drop leads there, and so does a cancel (pointercancel, lost capture, the page
 * hidden or left); both still get there if something in them throws. The click that follows a lift is swallowed,
 * so letting go never opens the app or folds the group. Nothing lifts while the page is offline: nothing saves.
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

  const CARD = ".apps > section[data-order] > ul:not([hidden]) > .app"; // a card that can be dragged
  const GROUP = ".apps > section.group[data-group][data-order]";        // a group that can be dragged
  // Where each kind of drop is saved, and what it sends: the keys (slugs or group ids) in their new order
  const SAVES = {
    pins: { url: "/api/prefs/pins", body: (keys) => ({ order: keys }) },
    group: { url: "/api/prefs/groups/apps", body: (keys, sec) => ({ id: sec.dataset.group, order: keys }) },
    groups: { url: "/api/prefs/groups/order", body: (keys) => ({ order: keys }) },
  };
  // What moves with a lifted card (the cards of its list) or group (the groups), in page order, and its key in a save
  const members = (block, list) =>
    [...list.children].filter((n) => n.matches(block ? "section.group[data-group]" : ".app"));
  const keyOf = (block, n) => (block ? n.dataset.group : n.dataset.slug);

  let press = null;  // a pointer held on a card or a group heading, not lifted yet
  let drag = null;   // the lifted card or group, until it has landed
  let swallow = 0;   // a click before this time is the one that follows a lift
  let saved = 0;     // number of the latest save
  const latest = new Map(); // what a drop saves ("groups", or a section id) -> number of its latest save

  // home.js: the click on a group heading that ends a hold must not fold the group
  window.hubDragJustEnded = () => performance.now() < swallow;

  const still = (e) => {
    if (root.dataset.hubDrag && e.cancelable) e.preventDefault();
  };

  function cancelPress() {
    if (!press) return;
    clearTimeout(press.timer);
    press = null;
  }

  // ------------------------------------------------------------------ lift
  // A refresh may have swapped the page since the press: find the card or group again, a card only in the section
  // it was pressed in
  function find(p) {
    if (p.block) return [...document.querySelectorAll(GROUP)].find((n) => n.dataset.group === p.key);
    return [...document.querySelectorAll(CARD)].find((n) => n.dataset.slug === p.key && n.closest("section").id === p.sec);
  }

  function lift() {
    const p = press;
    press = null;
    const el = find(p);
    if (!el) return;
    const sec = el.closest("section");
    const saver = SAVES[p.block ? "groups" : sec.dataset.order];
    if (!saver) return;
    try {
      el.setPointerCapture(p.id);
    } catch {
      return; // the pointer is no longer down
    }
    const list = el.parentElement;
    const items = members(p.block, list);
    const sx = scrollX, sy = scrollY;
    const slots = items.map((n) => {
      const r = n.getBoundingClientRect();
      return { x: r.left + sx, y: r.top + sy, w: r.width, h: r.height };
    });
    // The space below each one when stacked. Cards in a column share one gap; a closed group has a smaller margin
    // than an open one, so each group keeps its own (the last one's reaches whatever follows the groups)
    const gap = slots.length > 1 ? slots[1].y - slots[0].y - slots[0].h : 0;
    const gaps = slots.map((s, i) => {
      if (!p.block) return gap;
      if (i + 1 < slots.length) return slots[i + 1].y - s.y - s.h;
      const after = items[i].nextElementSibling;
      return after ? after.getBoundingClientRect().top + sy - s.y - s.h : parseFloat(getComputedStyle(items[i]).marginBottom) || 0;
    });
    el.classList.add("lifted");
    for (const n of items) if (n !== el) n.classList.add("sliding");
    getSelection()?.removeAllRanges();
    // A finger's touch events keep going to the node it first touched, even after a refresh took that node out
    // of the page; then they never reach the listener on document, and the page would scroll
    p.target.addEventListener("touchmove", still, { passive: false });
    const from = items.indexOf(el);
    drag = {
      id: p.id, el, list, items, slots, gaps, from, to: from, touched: p.target,
      block: p.block, // a whole group: up and down only, saved as the order of the groups
      url: saver.url, body: (keys) => saver.body(keys, sec), sec: sec.id,
      // One column (the list view on a phone, and the groups): cards can differ in height, so the others are
      // stacked, not put into each other's slots
      column: p.block || slots.every((s) => Math.abs(s.x - slots[0].x) < 1),
      x0: p.x + sx, y0: p.y + sy, // the pointer at the lift, in page coordinates
      x: p.x, y: p.y, sx, sy,     // the pointer now (viewport) and the scroll now
      moved: false, done: false,
    };
    root.dataset.hubDrag = "1"; // last, so a lift that got this far always has a drag that will clear it
  }

  // ------------------------------------------------------------------ move
  // The cards (or groups) in the order they would have if dropped at `to`
  function order(d, to = d.to) {
    const o = d.items.filter((n) => n !== d.el);
    o.splice(to, 0, d.el);
    return o;
  }
  // Where each one's top left corner goes in that order, in page coordinates
  function places(d, o) {
    const out = new Map();
    let y = d.slots[0].y;
    o.forEach((n, j) => {
      if (d.column) {
        out.set(n, { x: d.slots[0].x, y });
        const i = d.items.indexOf(n);
        y += d.slots[i].h + d.gaps[i];
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

  // Where a drop with the pointer at (px, py), page coordinates, would land
  function target(d, px, py) {
    let to = d.to, best = Infinity;
    if (d.block) {
      // The place for the group whose top is nearest to where its top is now
      const top = d.slots[d.from].y + py - d.y0;
      for (let t = 0; t < d.items.length; t++) {
        const dist = Math.abs(places(d, order(d, t)).get(d.el).y - top);
        if (dist < best) { best = dist; to = t; }
      }
      return to;
    }
    d.slots.forEach((s, i) => {
      const dist = Math.hypot(s.x + s.w / 2 - px, s.y + s.h / 2 - py);
      if (dist < best) { best = dist; to = i; }
    });
    return to;
  }

  function move(x, y) {
    const d = drag;
    d.x = x;
    d.y = y;
    // Page coordinates: when the page scrolls under a still pointer (a mouse wheel, say), the card stays under the
    // pointer and so moves on the page, which counts as moving it
    const px = x + d.sx, py = y + d.sy;
    if (!d.moved && Math.hypot(px - d.x0, py - d.y0) > SLOP) d.moved = true;
    // A group only goes up and down; sideways it would only widen the page
    d.el.style.transform = translate(d.block ? 0 : px - d.x0, py - d.y0);
    const to = target(d, px, py);
    if (to === d.to) return;
    d.to = to;
    const p = places(d, order(d));
    for (const n of d.items) if (n !== d.el) n.style.transform = offset(d, n, p.get(n));
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

  // Puts `want` (the nodes of `items` in a new order) where `items` are in `list`: the groups sit between Favourites
  // and the rest, so they go back in before whatever follows the last of them
  function arrange(list, items, want) {
    const anchor = items[items.length - 1].nextSibling;
    for (const n of want) list.insertBefore(n, anchor);
  }

  function drop(d) {
    swallow = performance.now() + 1000;
    d.done = true; // no second drop or cancel for this lift; end() follows exactly once, below or after the glide
    if (!d.moved) {
      // A long press. The menu opens before the flag is cleared, so a refresh waiting for hub:idle sees it open.
      try {
        if (!d.block && d.list.classList.contains("grid")) {
          document.dispatchEvent(new CustomEvent("hub:menu", { detail: { li: d.el, x: d.x, y: d.y } }));
        }
      } finally {
        end(d);
      }
      return;
    }
    try {
      const o = order(d);
      const before = d.items.map((x) => keyOf(d.block, x));
      const where = { block: d.block, sec: d.sec, key: d.block ? "groups" : d.sec };
      const n = d.to === d.from ? 0 : ++saved;
      if (n) latest.set(where.key, n);
      const sent = n ? save(d.url, d.body(o.map((x) => keyOf(d.block, x)))) : null; // now, not after the glide
      d.el.classList.add("sliding");
      d.el.style.transform = offset(d, d.el, places(d, o).get(d.el));
      settle(d, () => {
        if (!sent) return;
        arrange(d.list, d.items, o); // end() then takes the transforms off in the same frame: nothing jumps
        sent.then((ok) => { if (!ok) unsaved(n, where, before); }); // runs after end(), once this lift is over
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
  function save(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.ok, () => false);
  }

  // Save number n failed, and what it moved has landed
  function unsaved(n, where, before) {
    // A later save of the same section (or of the groups) sends its whole order again, and a card or group held
    // right now, or pressed and about to lift, must not move under the finger
    if (latest.get(where.key) === n && !drag && !press) restore(where, before);
    setTimeout(() => alert(JSON.parse(document.getElementById("__hub_strings").textContent).save_failed), SETTLE);
  }

  // Back to the order before the drop, gliding. Found by section and key: a refresh may have swapped the page
  // meanwhile.
  function restore(where, keys) {
    const list = where.block ? document.querySelector(".apps") : document.getElementById(where.sec)?.querySelector(":scope > ul");
    if (!list) return;
    const items = members(where.block, list);
    if (!items.length) return;
    const rank = (n) => {
      const i = keys.indexOf(keyOf(where.block, n));
      return i < 0 ? keys.length : i;
    };
    const want = [...items].sort((a, b) => rank(a) - rank(b));
    if (want.every((n, i) => n === items[i])) return;
    const was = new Map(items.map((n) => [n, n.getBoundingClientRect()]));
    arrange(list, items, want);
    for (const n of items) {
      const a = was.get(n), b = n.getBoundingClientRect();
      n.style.transform = translate(a.left - b.left, a.top - b.top);
    }
    void list.offsetWidth; // start from where they were...
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
    if (root.dataset.hubOffline) return;
    const group = at(e, ".gtoggle")?.closest(GROUP);
    const li = group ? null : at(e, CARD);
    if (!group && !li) return;
    press = {
      id: e.pointerId, block: !!group, key: group ? group.dataset.group : li.dataset.slug,
      sec: (group || li.closest("section")).id, mouse: e.pointerType === "mouse", target: e.target,
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
  // Also sent when a touch's own capture moves to the lifted element; only losing that element's capture cancels
  document.addEventListener("lostpointercapture", (e) => {
    if (drag && !drag.done && e.pointerId === drag.id && (e.target === drag.el || !drag.el.isConnected)) cancel(drag);
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

  // The page stays still while something is lifted
  document.addEventListener("touchmove", still, { passive: false });
  document.addEventListener("click", (e) => {
    if (performance.now() >= swallow) return;
    swallow = 0;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  // No native link drag with the mouse, and no system menu (Android's long press) while a finger holds a card
  document.addEventListener("dragstart", (e) => { if (at(e, ".apps > section[data-order]")) e.preventDefault(); });
  document.addEventListener("contextmenu", (e) => {
    if (!drag && !(press && !press.mouse)) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
})();
