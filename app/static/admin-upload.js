// The Upload tab: files and link cards. The page is not reloaded; the log shows the result.
(() => {
  const { T, $, fmt, reach } = window.Admin;
  const drop = $('drop'), input = $('file'), log = $('log');

  function note(msg, ok = true) {
    const li = document.createElement('li');
    li.textContent = msg; li.className = ok ? 'ok' : 'err';
    log.prepend(li);
    return li;
  }

  async function upload(file) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('admin_only', $('adminOnly').checked ? 'true' : 'false');
    const busy = note(fmt(T.uploading, { name: file.name }));
    const r = await reach(fetch('/api/upload', { method: 'POST', body: fd }));
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      const link = document.createElement('a');
      link.href = link.textContent = j.url;
      note(`✓ ${file.name} → `).append(link);
    } else {
      busy.remove();
      note(`✗ ${file.name}: ${j.detail || r.status}`, false);
    }
  }

  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => [...e.dataTransfer.files].forEach(upload));
  input.addEventListener('change', () => {
    const files = [...input.files];
    input.value = '';  // so the same file can be chosen again
    files.forEach(upload);
  });

  $('linkForm').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData(form);
    fd.append('admin_only', $('adminOnly').checked ? 'true' : 'false');
    const r = await reach(fetch('/api/link', { method: 'POST', body: fd }));
    const j = await r.json().catch(() => ({}));
    if (r.ok) { note(fmt(T.linkAdded, { title: fd.get('title') })); form.reset(); }
    else note(`✗ ${j.detail || r.status}`, false);
  });
})();
