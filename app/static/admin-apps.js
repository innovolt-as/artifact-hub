// The Apps tab: the list, the search, the settings sheet per app, and the edit, access and shared-data dialogs.
(() => {
  const { T, $, fmt, postJson, failText } = window.Admin;
  const sheet = $('appSheet');
  let current = null;  // the slug of the app in the sheet

  const rows = () => [...$('appList').querySelectorAll('li[data-slug]')];
  const rowOf = slug => rows().find(li => li.dataset.slug === slug);

  // An error shows in the sheet of the app it is about, otherwise under the list
  function fail(msg, slug = current) {
    if (sheet.open && slug === current) { $('asError').textContent = msg; return; }
    const li = document.createElement('li');
    li.textContent = `✗ ${slug ? slug + ': ' : ''}${msg}`; li.className = 'err';
    $('log').prepend(li);
  }
  // A network failure, or the hub's redirect to the login page (fetch follows it and sees a 200), reads like a failed
  // response, so each caller has one error path
  const failed = (status, detail) => ({ ok: false, status, json: async () => ({ detail }) });
  const reach = p => p.then(r => r.redirected ? failed(401, T.loggedOut) : r).catch(() => failed(0, T.netError));
  const why = r => r.status === 404 ? T.appGone : failText(r);
  function postSlug(url, slug) {
    const fd = new FormData(); fd.append('slug', slug);
    return reach(fetch(url, { method: 'POST', body: fd }));
  }

  // --- search
  function search() {
    const q = $('appSearch').value.trim().toLowerCase();
    const all = rows();
    for (const li of all) li.hidden = !(li.dataset.title + ' ' + li.dataset.slug).toLowerCase().includes(q);
    const shown = all.filter(li => !li.hidden).length;
    $('appCount').hidden = !q;
    $('appCount').textContent = fmt(T.searchCount, { shown, total: all.length });
    $('appList').hidden = all.length > 0 && !shown;
    $('appNone').hidden = !$('appList').hidden;
  }
  $('appSearch').addEventListener('input', search);
  search();  // the browser may have kept the text from before a reload

  // --- the list follows the hub without a page load
  let refreshes = 0;
  async function refresh() {
    const mine = ++refreshes;
    let doc = null;
    try {
      const r = await reach(fetch('/admin', { cache: 'no-store' }));
      if (r.ok) doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    } catch { return false; }
    const fresh = doc && doc.getElementById('appList');
    if (!fresh) return false;  // an error, or logged out: /admin then ends on the login page
    if (mine !== refreshes) return true;  // a newer refresh is on its way, and an older answer must not win
    known = JSON.parse(doc.getElementById('known').textContent);  // a person just added to one app, for the next
    $('appList').replaceChildren(...fresh.childNodes);
    search();
    if (sheet.open) {
      const li = rowOf(current);
      if (li) render(li); else sheet.close();
    }
    return true;
  }
  async function saved() {
    $('asError').textContent = '';
    if (!await refresh()) fail(T.refreshFailed);
  }

  // --- the sheet
  function render(li) {
    const d = li.dataset, link = d.kind === 'link';
    $('asIcon').replaceChildren(li.querySelector('.icon').cloneNode(true));
    $('asTitle').textContent = d.title;
    $('asAddress').textContent = `${d.url} · ${d.kindlabel}`;
    $('asOpen').href = d.url;
    $('asOpen').target = link ? '_blank' : '';
    $('asOpen').rel = link ? 'noopener' : '';
    $('asWarn').hidden = d.warned !== '1';
    $('asAccessLabel').textContent = d.label;
    $('asSwitches').hidden = link;
    $('asData').checked = d.shared === '1';
    $('asBanner').checked = d.banner === '1';
  }
  let openedAt = 0;
  function open(li) {
    current = li.dataset.slug;
    $('asError').textContent = '';
    render(li);
    sheet.showModal();
    openedAt = performance.now();
  }
  $('appList').addEventListener('click', e => {
    const row = e.target.closest('.arow');
    if (row) open(row.closest('li'));
  });
  $('asClose').onclick = () => sheet.close();
  // The second click of the double click that opened the sheet lands in it, and must not close it or change a setting
  sheet.addEventListener('click', e => {
    if (performance.now() - openedAt < 350) { e.preventDefault(); e.stopPropagation(); }
  }, true);
  sheet.addEventListener('click', e => { if (e.target === sheet) sheet.close(); });  // the backdrop
  sheet.addEventListener('close', () => {
    // The tapped row may have been replaced since, so the browser cannot always put the focus back by itself
    const li = rowOf(current);
    current = null;
    if (li && !li.hidden) li.querySelector('.arow').focus();
    else $('appsHeading').focus({ preventScroll: true });  // the row is gone: the list stays where it is
  });

  // One save at a time: a tap on a switch while one runs does nothing
  let busy = false;
  for (const box of [$('asData'), $('asBanner')]) box.addEventListener('click', e => { if (busy) e.preventDefault(); });
  // work() saves and returns the response, or null when a dialog takes over from here
  async function flip(work) {
    const slug = current;
    busy = true;
    $('asError').textContent = '';
    try {
      const r = await work();
      if (r && r.ok) await saved();
      else if (r) {
        const li = rowOf(current);  // the row knows what is saved, and by now the sheet may show another app
        if (li) render(li);
        fail(await why(r), slug);
      }
    } finally { busy = false; }
  }
  $('asBanner').addEventListener('change', () => flip(() => postSlug('/api/toggle-banner', current)));

  $('asDelete').onclick = async () => {
    const slug = current, btn = $('asDelete');
    if (!confirm(fmt(T.confirmDelete, { slug }))) return;
    $('asError').textContent = '';
    btn.disabled = true;
    const r = await postSlug('/api/delete', slug);
    btn.disabled = false;
    if (!r.ok) return fail(await why(r), slug);
    rowOf(slug)?.remove();
    sheet.close();
    await saved();
  };

  // --- edit dialog: name, address, emoji, image
  const ed = $('editor');
  const f = $('editForm');
  let editing = null, objectUrl = null;

  function preview() {
    const pv = $('pvIcon');
    pv.style.setProperty('--hue', editing.hue);
    pv.replaceChildren();
    const file = $('edIcon').files[0];
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
    const src = file ? (objectUrl = URL.createObjectURL(file)) : ($('edRemove').checked ? '' : editing.icon);
    const el = document.createElement(src ? 'img' : 'span');
    if (src) { el.src = src; el.alt = ''; }
    else if ($('edEmoji').value.trim()) { el.className = 'emoji'; el.textContent = $('edEmoji').value.trim(); }
    else { el.className = 'letter'; el.textContent = ($('edTitle').value.trim()[0] || '?').toUpperCase(); }
    pv.append(el);
  }

  $('asEdit').onclick = () => {
    editing = rowOf(current).dataset;
    const link = editing.kind === 'link';
    f.reset();
    $('edTitle').value = editing.title;
    $('edSlug').value = editing.slug;
    $('edEmoji').value = editing.emoji;
    $('edSlugRow').hidden = link;   // link cards have an external URL instead
    $('edUrlRow').hidden = !link;
    $('edUrl').value = link ? editing.url : '';
    $('edRemoveRow').hidden = !editing.icon;
    $('edError').textContent = '';
    preview();
    ed.showModal();
  };
  ['edTitle', 'edEmoji', 'edIcon', 'edRemove'].forEach(id => $(id).addEventListener('input', preview));
  $('edCancel').onclick = () => ed.close();

  f.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(f);
    fd.append('slug', current);
    if (!$('edIcon').files.length) fd.delete('icon');
    const r = await reach(fetch('/api/edit', { method: 'POST', body: fd }));
    if (!r.ok) { $('edError').textContent = await why(r); return; }
    current = (await r.json()).slug;  // the address may be new
    ed.close();
    await saved();
  });

  // --- access dialog: everyone, the checked people, or only me (the list is kept whatever is chosen)
  const acDlg = $('accessDlg'), acForm = $('accessForm');
  let known = JSON.parse($('known').textContent), acClaude = false;

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

  $('asAccess').onclick = () => {
    const d = rowOf(current).dataset;
    acClaude = d.claude === '1';
    const mine = JSON.parse(d.people);
    $('acTitle').textContent = d.title;
    acForm.level.value = d.level;
    $('acList').replaceChildren(...[...new Set([...mine, ...known])].sort().map(e => personRow(e, mine.includes(e))));
    $('acNew').value = '';
    $('acError').textContent = '';
    showPeople();
    acDlg.showModal();
  };
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
    const r = await reach(postJson('/api/access', { slug: current, level: acForm.level.value, people }));
    if (!r.ok) { $('acError').textContent = await why(r); return; }
    acDlg.close();
    await saved();
  });

  // --- shared data: everyone who can see the app reads it, only admins change it (app/shared.py)
  const shDlg = $('shareDlg');
  const setData = (shared, copy) => reach(postJson('/api/data-mode', { slug: current, shared, copy }));

  function showShare(p) {
    const canCopy = p.docs > 0 && !p.shared_exists;
    $('shTitle').textContent = rowOf(current).dataset.title;
    $('shMine').textContent = fmt(T.shareMine, { collections: Object.entries(p.collections).map(([c, n]) => `${c} (${n})`).join(', ') });
    $('shMine').hidden = !canCopy;
    $('shOthers').textContent = fmt(T.shareOthers, { n: p.others });
    $('shOthers').hidden = !p.others;
    $('shExists').hidden = !p.shared_exists;
    $('shCopy').hidden = !canCopy;
    $('shEmpty').textContent = canCopy ? T.shareEmpty : T.shareOn;
    shDlg.showModal();
  }
  $('asData').addEventListener('change', e => flip(async () => {
    if (!e.target.checked) return setData(false, false);
    const slug = current;
    const r = await reach(fetch('/api/data-mode?slug=' + encodeURIComponent(slug)));
    if (!r.ok) return r;
    const p = await r.json();
    if (current === slug) showShare(p);  // unless the sheet was closed while this was on its way
    return null;
  }));
  async function share(copy) {
    const slug = current;
    const r = await setData(true, copy);
    if (r.ok) await saved();
    shDlg.close();
    if (!r.ok) fail(await why(r), slug);
  }
  $('shCopy').onclick = () => share(true);
  $('shEmpty').onclick = () => share(false);
  $('shCancel').onclick = () => shDlg.close();
  // However the dialog closes (Cancel, Esc, a save), the switch says what the app has now
  shDlg.addEventListener('close', () => { $('asData').checked = rowOf(current)?.dataset.shared === '1'; });
})();
