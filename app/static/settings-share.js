// Settings, shared links section (templates/settings.html): one row per link with copy, new link, turn off and clear
// guests' replies. The last three ask first, in the row. Same routes as the banner's sheet (static/share.js).
(function () {
  const card = document.getElementById("shareCard");
  let T = {};
  try { T = JSON.parse(card.dataset.strings || "{}"); } catch { /* texts stay empty */ }
  const fmt = (s, vars) => String(s || "").replace(/\{(\w+)\}/g, (_, k) => vars[k]);
  const QUESTION = { rotate: T.confirm_rotate, off: T.confirm_off, clear: T.confirm_clear };

  // {ok, state} or {ok: false, locked}; 423: the app is locked and not unlocked on this device
  async function post(row, action) {
    try {
      const r = await fetch(`/api/share/${encodeURIComponent(row.dataset.slug)}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: row.dataset.name, action }),
      });
      return r.ok ? { ok: true, state: await r.json() } : { ok: false, locked: r.status === 423 };
    } catch {
      return { ok: false, locked: false };
    }
  }

  const clearButton = (row) => row.querySelector('[data-act="clear"]');
  function showCount(row, n) {
    row.querySelector(".scount").textContent = fmt(T[n === 1 ? "guests.one" : "guests.other"], { n });
    clearButton(row).disabled = n === 0;
  }

  async function copy(row, button) {
    const input = row.querySelector(".surl");
    let done = false;
    try { await navigator.clipboard.writeText(input.value); done = true; } catch { /* select it below */ }
    if (!done) {
      input.focus();
      input.select();
      input.setSelectionRange(0, input.value.length);
      try { done = document.execCommand("copy"); } catch { /* the text stays selected for the user */ }
    }
    if (!done) return;
    button.textContent = T.copied;
    setTimeout(() => { button.textContent = T.copy; }, 2000);
  }

  function ask(row, action) {
    const box = row.querySelector(".sask");
    const mk = (label, cls, fn) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      if (cls) b.className = cls;
      b.addEventListener("click", fn);
      return b;
    };
    const question = document.createElement("p");
    question.textContent = QUESTION[action];
    const buttons = document.createElement("div");
    buttons.className = "sacts";
    const close = () => { box.hidden = true; box.replaceChildren(); row.querySelector(".sacts").hidden = false; };
    const yes = mk(T.confirm, "danger", () => { close(); run(row, action); });
    buttons.append(yes, mk(T.cancel, "", close));
    box.replaceChildren(question, buttons);
    row.querySelector(".sacts").hidden = true;
    box.hidden = false;
    yes.focus();
  }

  let busy = false;
  async function run(row, action) {
    if (busy) return;
    busy = true;
    const err = row.querySelector(".err");
    err.textContent = "";
    const r = await post(row, action);
    busy = false;
    if (!r.ok) {
      err.textContent = r.locked ? T.locked_error : T.failed;
      return;
    }
    if (!r.state.link) {  // turned off: the row goes, and the card when it was the last
      row.remove();
      if (!card.querySelector(".srow")) card.remove();
      return;
    }
    row.querySelector(".surl").value = r.state.link.url;
    row.querySelector(".swarn").hidden = r.state.ready !== false;
    showCount(row, r.state.guest_docs);
  }

  for (const b of card.querySelectorAll('[data-act="send"]')) b.hidden = !navigator.share;
  card.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const row = b.closest(".srow"), act = b.dataset.act;
    if (act === "copy") copy(row, b);
    else if (act === "send") {
      const url = row.querySelector(".surl").value;
      navigator.share({ url }).catch(() => {});
    } else ask(row, act);
  });
})();
