// Shared helpers for the admin pages; each tab's own script reads them from window.Admin.
window.Admin = (() => {
  const T = JSON.parse(document.getElementById('__admin_strings').textContent);
  const $ = id => document.getElementById(id);
  const fmt = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => k in vars ? vars[k] : m);
  const postJson = (url, body) =>
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const failText = async r => (await r.json().catch(() => ({}))).detail || fmt(T.errorStatus, { status: r.status });
  return { T, $, fmt, postJson, failText };
})();
