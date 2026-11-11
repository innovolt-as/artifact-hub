// The share sheet of an app's banner (app/banner.py puts the button and an empty sheet in the banner's shadow root; this
// file is loaded only on owner pages of apps with public sharing). It acts on the share name and title the app set last
// with share.scope() (hub.js keeps them in window.claude.__share). It shows the link and how many replies guests have
// left, never the replies themselves.
(function () {
  const me = document.currentScript;
  const SLUG = me && me.dataset.slug;
  let T = {};
  try { T = JSON.parse((me && me.dataset.strings) || "{}"); } catch { /* texts stay empty */ }
  const fmt = (s, vars) => String(s || "").replace(/\{(\w+)\}/g, (_, k) => vars[k]);

  // The state ({link, guest_docs, locked}) of one share name, or after an action {ok: false, locked?} with no state.
  // A 423 means the app is locked and not unlocked on this device.
  async function request(slug, name, body) {
    const url = `/api/share/${encodeURIComponent(slug)}`;
    try {
      const r = body
        ? await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, ...body }),
          })
        : await fetch(`${url}?name=${encodeURIComponent(name)}`, { credentials: "same-origin" });
      if (!r.ok) return { ok: false, locked: r.status === 423 };
      return { ok: true, state: await r.json() };
    } catch {
      return { ok: false, locked: false };
    }
  }
  window.hubShare = { request };

  function el(tag, props, ...kids) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    if (props && props.role) e.setAttribute("role", props.role);  // the property is new in some browsers
    e.append(...kids);
    return e;
  }

  function init() {
    const host = document.querySelector("hub-banner");
    const root = host && host.shadowRoot;
    const button = root && root.querySelector("button.share");
    const sheet = root && root.querySelector("dialog.sheet");
    if (!button || !sheet) return;
    const body = sheet.querySelector(".body");
    let busy = false;

    const current = () => (window.claude && window.claude.__share) || { name: "main", title: "" };
    const close = () => { if (sheet.close) sheet.close(); else sheet.removeAttribute("open"); };
    sheet.querySelector(".x").addEventListener("click", close);
    sheet.addEventListener("click", (e) => { if (e.target === sheet) close(); });  // a tap on the dim area

    // What the sheet shows: the explanation, then "Create link" or the link with its actions
    function show(state, message) {
      const { title } = current();
      const parts = [el("p", { textContent: T.explain })];
      if (title) parts.push(el("p", { className: "muted", textContent: fmt(T.for, { title }) }));
      if (!state.link) {
        parts.push(action(T.create, "pri", () => run({ action: "create", title })));
      } else {
        const url = el("input", { type: "text", readOnly: true, value: state.link.url });
        url.setAttribute("aria-label", T.link);
        url.addEventListener("focus", () => url.select());
        const copy = el("button", { type: "button", className: "pri", textContent: T.copy });
        copy.addEventListener("click", () => copyUrl(url, copy));
        const row = [copy];
        if (navigator.share) {
          const send = el("button", { type: "button", textContent: T.send });
          send.addEventListener("click", () => navigator.share({ url: state.link.url, title: state.link.title || undefined }).catch(() => {}));
          row.push(send);
        }
        parts.push(url, el("div", { className: "acts" }, ...row));
        if (state.locked) parts.push(el("p", { className: "muted", textContent: T.locked_note }));
        const n = state.guest_docs;
        parts.push(el("p", { className: "muted", textContent: fmt(T[n === 1 ? "guests.one" : "guests.other"], { n }) }));
        const more = el("div", { className: "acts" },
          ask(T.rotate, T.confirm_rotate, { action: "rotate" }),
          ask(T.off, T.confirm_off, { action: "off" }),
          ask(T.clear, T.confirm_clear, { action: "clear" }, n === 0));
        parts.push(more);
      }
      parts.push(el("p", { className: "err", role: "alert", textContent: message || "" }));
      body.replaceChildren(...parts);
    }

    function action(label, cls, fn, disabled) {
      const b = el("button", { type: "button", className: cls, textContent: label, disabled: !!disabled });
      b.addEventListener("click", fn);
      return b;
    }

    // A button that first asks "sure?" in place of the actions, then runs the action
    function ask(label, question, payload, disabled) {
      return action(label, "", () => {
        const yes = action(T.confirm, "dng", () => run(payload));
        const no = action(T.cancel, "", () => load());
        body.replaceChildren(el("div", { className: "ask" }, el("p", { textContent: question }),
          el("div", { className: "acts" }, yes, no)));
        yes.focus();
      }, disabled);
    }

    async function copyUrl(input, copy) {
      let done = false;
      try { await navigator.clipboard.writeText(input.value); done = true; } catch { /* no clipboard: select it below */ }
      if (!done) {
        input.focus();
        input.select();
        input.setSelectionRange(0, input.value.length);
        try { done = document.execCommand("copy"); } catch { /* the text stays selected for the user */ }
      }
      if (!done) return;
      copy.textContent = T.copied;
      setTimeout(() => { copy.textContent = T.copy; }, 2000);
    }

    async function run(payload) {
      if (busy) return;
      busy = true;
      const r = await request(SLUG, current().name, payload);
      busy = false;
      if (r.ok) show(r.state);
      else load(r.locked ? T.locked_error : T.failed);
    }

    async function load(message) {
      body.replaceChildren(el("p", { className: "muted", textContent: T.loading }));
      const r = await request(SLUG, current().name);
      if (r.ok) show(r.state, message);
      else body.replaceChildren(el("p", { className: "err", role: "alert", textContent: T.failed }));
    }

    button.addEventListener("click", () => {
      if (sheet.showModal) sheet.showModal(); else sheet.setAttribute("open", "");  // very old browsers: no top layer
      load();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
