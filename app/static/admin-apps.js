// The Apps tab: the list's buttons and the edit, access and shared-data dialogs.
(() => {
  const { T, $, fmt, postJson, failText } = window.Admin;
  const log = $('log');

  function note(msg, ok = true) {
    const li = document.createElement('li');
    li.textContent = msg; li.className = ok ? 'ok' : 'err';
    log.prepend(li);
  }

  async function post(url, slug) {
    const fd = new FormData(); fd.append('slug', slug);
    const r = await fetch(url, { method: 'POST', body: fd });
    if (!r.ok) { const j = await r.json().catch(() => ({})); note(`✗ ${j.detail || r.status}`, false); return false; }
    return true;
  }
  document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    if (!confirm(fmt(T.confirmDelete, { slug: b.dataset.slug }))) return;
    if (await post('/api/delete', b.dataset.slug)) b.closest('tr').remove();
  });
  document.querySelectorAll('.banner').forEach(b => b.onclick = async () => {
    if (await post('/api/toggle-banner', b.dataset.slug)) location.reload();
  });

  // --- edit dialog: name, address, emoji, image
  const ed = $('editor');
  const f = $('editForm');
  let current = null, objectUrl = null;

  function preview() {
    const pv = $('pvIcon');
    pv.style.setProperty('--hue', current.hue);
    pv.replaceChildren();
    const file = $('edIcon').files[0];
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
    const src = file ? (objectUrl = URL.createObjectURL(file)) : ($('edRemove').checked ? '' : current.icon);
    const el = document.createElement(src ? 'img' : 'span');
    if (src) { el.src = src; el.alt = ''; }
    else if ($('edEmoji').value.trim()) { el.className = 'emoji'; el.textContent = $('edEmoji').value.trim(); }
    else { el.className = 'letter'; el.textContent = ($('edTitle').value.trim()[0] || '?').toUpperCase(); }
    pv.append(el);
  }

  document.querySelectorAll('.edit').forEach(b => b.onclick = () => {
    current = b.dataset;
    f.reset();
    $('edTitle').value = current.title;
    $('edSlug').value = current.slug;
    $('edEmoji').value = current.emoji;
    $('edSlugRow').hidden = current.kind === 'link';   // link cards have an external URL instead
    $('edUrlRow').hidden = current.kind !== 'link';
    $('edUrl').value = current.url;
    $('edRemoveRow').hidden = !current.icon;
    $('edError').textContent = '';
    preview();
    ed.showModal();
  });
  ['edTitle', 'edEmoji', 'edIcon', 'edRemove'].forEach(id => $(id).addEventListener('input', preview));
  $('edCancel').onclick = () => ed.close();

  f.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(f);
    fd.append('slug', current.slug);
    if (!$('edIcon').files.length) fd.delete('icon');
    const r = await fetch('/api/edit', { method: 'POST', body: fd });
    if (r.ok) return location.reload();
    const j = await r.json().catch(() => ({}));
    $('edError').textContent = j.detail || fmt(T.errorStatus, { status: r.status });
  });

  // --- access dialog: everyone, the checked people, or only me (the list is kept whatever is chosen)
  const acDlg = $('accessDlg'), acForm = $('accessForm');
  const known = JSON.parse($('known').textContent);
  let acSlug = null, acClaude = false;

  function personRow(email, checked) {
    const li = document.createElement('li');
    const label = document.createElement('label');
    label.className = 'check';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.value = email; cb.checked = checked;
    label.append(cb, ' ' + email);
    li.append(label);
    return li;
  }
  // Claude fills the app with an admin's personal data: warn as soon as others than admins would see it
  function showWarn() {
    const level = acForm.level.value;
    const someone = $('acList').querySelector('input:checked') !== null;
    $('acWarn').hidden = !(acClaude && (level === 'all' || (level === 'people' && someone)));
  }
  const showPeople = () => { $('acPeople').hidden = acForm.level.value !== 'people'; showWarn(); };
  $('acList').addEventListener('change', showWarn);

  document.querySelectorAll('.access').forEach(b => b.onclick = () => {
    acSlug = b.dataset.slug;
    acClaude = b.dataset.claude === '1';
    const mine = JSON.parse(b.dataset.people);
    $('acTitle').textContent = b.dataset.title;
    acForm.level.value = b.dataset.level;
    $('acList').replaceChildren(...[...new Set([...mine, ...known])].sort().map(e => personRow(e, mine.includes(e))));
    $('acNew').value = '';
    $('acError').textContent = '';
    showPeople();
    acDlg.showModal();
  });
  acForm.querySelectorAll('input[name=level]').forEach(r => r.onchange = showPeople);

  function addPerson() {
    const input = $('acNew'), email = input.value.trim().toLowerCase();
    if (!email) return true;
    if (!input.checkValidity()) { $('acError').textContent = T.validEmail; return false; }
    const row = [...$('acList').querySelectorAll('input')].find(cb => cb.value === email);
    if (row) row.checked = true;
    else $('acList').prepend(personRow(email, true));
    showWarn();
    input.value = '';
    $('acError').textContent = '';
    return true;
  }
  $('acAdd').onclick = addPerson;
  $('acNew').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addPerson(); } });
  $('acCancel').onclick = () => acDlg.close();

  acForm.addEventListener('submit', async e => {
    e.preventDefault();
    if (!addPerson()) return;  // an address typed but not added yet still counts
    const people = [...$('acList').querySelectorAll('input:checked')].map(cb => cb.value);
    const r = await postJson('/api/access', { slug: acSlug, level: acForm.level.value, people });
    if (r.ok) return location.reload();
    $('acError').textContent = await failText(r);
  });

  // --- shared data: everyone who can see the app reads it, only admins change it (app/shared.py)
  const shDlg = $('shareDlg');
  let shSlug = null;
  async function setData(slug, shared, copy) {
    const r = await postJson('/api/data-mode', { slug, shared, copy });
    if (r.ok) return location.reload();
    shDlg.close();
    note(`✗ ${await failText(r)}`, false);
  }
  document.querySelectorAll('.datamode').forEach(b => b.onclick = async () => {
    if (b.dataset.shared === '1') return setData(b.dataset.slug, false, false);
    const r = await fetch('/api/data-mode?slug=' + encodeURIComponent(b.dataset.slug));
    if (!r.ok) return note(`✗ ${await failText(r)}`, false);
    const p = await r.json();
    const canCopy = p.docs > 0 && !p.shared_exists;
    shSlug = b.dataset.slug;
    $('shTitle').textContent = b.dataset.title;
    $('shMine').textContent = fmt(T.shareMine, { collections: Object.entries(p.collections).map(([c, n]) => `${c} (${n})`).join(', ') });
    $('shMine').hidden = !canCopy;
    $('shOthers').textContent = fmt(T.shareOthers, { n: p.others });
    $('shOthers').hidden = !p.others;
    $('shExists').hidden = !p.shared_exists;
    $('shCopy').hidden = !canCopy;
    $('shEmpty').textContent = canCopy ? T.shareEmpty : T.shareOn;
    shDlg.showModal();
  });
  $('shCancel').onclick = () => shDlg.close();
  $('shCopy').onclick = () => setData(shSlug, true, true);
  $('shEmpty').onclick = () => setData(shSlug, true, false);
})();
