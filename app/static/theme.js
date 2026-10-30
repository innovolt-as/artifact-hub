// A page restored from the browser's page cache still has the theme it was served with; a choice made on /settings since
// then waits in sessionStorage. Only on a restore: on a normal load what the server sent stands. base.html loads this for
// logged-in users only. It must stay out of pull.js, which also runs in apps: sessionStorage is shared with /a/..., and
// the theme must never touch an app.
addEventListener("pageshow", (e) => {
  if (!e.persisted) return;
  let theme;
  try { theme = sessionStorage.getItem("hub-theme"); } catch { return; }
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
});
