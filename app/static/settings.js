// Settings page: the theme applies at once (data-theme on <html>) and is saved to the account;
// if saving fails the choice and data-theme go back to what they were.
(function () {
  const seg = document.querySelector("fieldset.seg");
  const err = document.getElementById("settingsError");
  const root = document.documentElement;
  const apply = (v) => { if (v === "auto") delete root.dataset.theme; else root.dataset.theme = v; };
  let saved = (seg.querySelector("input:checked") || {}).value || "auto";
  seg.addEventListener("change", (e) => {
    const v = e.target.value;
    err.textContent = "";
    apply(v);
    fetch("/api/prefs/theme", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: v }),
    }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      saved = v;
      // For a page that comes back from the browser's page cache (theme.js)
      try { sessionStorage.setItem("hub-theme", v); } catch { /* blocked: that page keeps its old theme */ }
    }).catch(() => {
      apply(saved);
      const back = seg.querySelector('input[value="' + saved + '"]');
      if (back) back.checked = true;
      err.textContent = seg.dataset.failed;
    });
  });
  // Back from the page cache, the choice may have been made on a later copy of this page: theme.js, which loads first,
  // has put data-theme right, and the buttons follow it
  addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    saved = root.dataset.theme || "auto";
    seg.querySelector('input[value="' + saved + '"]').checked = true;
  });
})();
