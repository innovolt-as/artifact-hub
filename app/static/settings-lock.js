// Settings, code lock section (templates/settings.html): choose or change the code, and a switch per app.
// On goes through at once. Off asks for the code in a dialog; a wrong code leaves the switch on.
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
        }
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
