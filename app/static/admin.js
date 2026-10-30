// Shared helpers for the admin pages; each tab's own script reads them from window.Admin.
window.Admin = (() => {
  const T = JSON.parse(document.getElementById('__admin_strings').textContent);
  const $ = id => document.getElementById(id);
  const fmt = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => k in vars ? vars[k] : m);
  const postJson = (url, body) =>
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const failText = async r => (await r.json().catch(() => ({}))).detail || fmt(T.errorStatus, { status: r.status });
  // A network failure, or the hub's redirect to the login page (fetch follows it and sees a 200), reads like a failed
  // response, so each caller has one error path
  const failed = (status, detail) => ({ ok: false, status, json: async () => ({ detail }) });
  const reach = p => p.then(r => r.redirected ? failed(401, T.loggedOut) : r).catch(() => failed(0, T.netError));
  return { T, $, fmt, postJson, failText, failed, reach };
})();
