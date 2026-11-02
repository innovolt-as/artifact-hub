// Settings, code lock section (templates/settings.html): choose or change the code, and a switch per app.
// On goes through at once. Off asks for the code in a dialog; a wrong code leaves the switch on.
// A locked app is never kept on the phone (static/sw.js): on also forgets its copy here and tells the hub's worker.
(function () {
  const card = document.getElementById("lockCard");
  const err = document.getElementById("lockError");
  const form = document.getElementById("lockCode");
  const ask = document.getElementById("lockAsk");
  const askErr = document.getElementById("lockAskError");

  // Returns {ok, detail}; a failed request has no detail, so the caller shows data-failed
  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(async (r) => {
      let detail = "";
      if (!r.ok) {
        try { detail = (await r.json()).detail; } catch { /* not JSON */ }
      }
      return { ok: r.ok, detail: typeof detail === "string" ? detail : "" };
    }).catch(() => ({ ok: false, detail: "" }));
  window.hubPost = post;  // settings-account.js, which loads after this file

  // The hub's own worker, once active: the one register() gives (navigator.serviceWorker.ready may be an app's own)
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
  // The app's page and folder files go from the copies here, also with no worker in control, and the worker drops it
  // from its list. Only that app's: the hub's other copies and the app's own storage stay.
  async function forgetCopy(slug) {
    const here = async () => {
      if (!window.caches || !(await caches.has("hub-pages-v1"))) return;
      const cache = await caches.open("hub-pages-v1"), prefix = new URL(`/a/${slug}/`, location.origin).href;
      for (const req of await cache.keys()) if (req.url.startsWith(prefix)) await cache.delete(req);
    };
    const worker = async () => {
      const user = document.querySelector("a.who")?.textContent.trim();
      if (!navigator.serviceWorker || !user) return;
      (await hubWorker(navigator.serviceWorker))?.postMessage({ type: "hub:app", user, slug, offline: false, assets: [] });
    };
    await Promise.all([here().catch(() => {}), worker().catch(() => {})]);
  }

  const digits = (el) => { el.value = el.value.replace(/[^0-9]/g, ""); };
  card.addEventListener("input", (e) => { if (e.target.classList.contains("code")) digits(e.target); });
  if (ask) ask.addEventListener("input", (e) => digits(e.target));

  // Each try with a code costs an attempt, so a form is sent once at a time
  let busy = false;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    busy = true;
    err.textContent = "";
    const body = {};
    for (const el of form.querySelectorAll("input.code")) body[el.name] = el.value;
    const r = await post("/api/lock/code", body);
    busy = false;
    if (r.ok) return location.reload();
    err.textContent = r.detail || card.dataset.failed;
  });

  const switches = card.querySelectorAll('input[role="switch"]');
  let asking = null;  // the switch the dialog is about

  for (const sw of switches) {
    sw.addEventListener("change", async () => {
      err.textContent = "";
      if (sw.checked) {
        const r = await post("/api/lock/apps", { slug: sw.dataset.slug, on: true });
        if (!r.ok) {
          sw.checked = false;
          err.textContent = r.detail || card.dataset.failed;
          return;
        }
        await forgetCopy(sw.dataset.slug);
        return;
      }
      sw.checked = true;  // stays on until the code is right
      asking = sw;
      askErr.textContent = "";
      ask.querySelector("input.code").value = "";
      ask.showModal();
    });
  }

  if (!ask) return;
  document.getElementById("lockAskCancel").addEventListener("click", () => ask.close());
  ask.addEventListener("close", () => { asking = null; });
  document.getElementById("lockAskForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy || !asking) return;
    busy = true;
    const field = ask.querySelector("input.code");
    const r = await post("/api/lock/apps", { slug: asking.dataset.slug, on: false, code: field.value });
    busy = false;
    if (r.ok) {
      asking.checked = false;
      ask.close();
      return;
    }
    askErr.textContent = r.detail || card.dataset.failed;
    field.value = "";
    field.focus();
  });
})();
