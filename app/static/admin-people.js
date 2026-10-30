// The People tab: invitations, temporary passwords and removal.
(() => {
  const { T, $, fmt, postJson, failText, reach } = window.Admin;

  $('inviteForm').addEventListener('submit', async e => {
    e.preventDefault();
    const body = { email: e.target.email.value };
    if (e.target.password) body.password = e.target.password.value;
    const r = await reach(postJson('/api/people/invite', body));
    if (r.ok) {
      $('peopleError').textContent = '';
      if (!e.target.password) return location.reload();
      // password mode: keep the page so the admin can pass the password on; reload when they click OK
      e.target.querySelectorAll('input, button').forEach(x => x.disabled = true);
      $('peopleError').classList.remove('err');
      $('peopleError').innerHTML = '';
      $('peopleError').append(T.invitedNote);
      const ok = document.createElement('button'); ok.className = 'small'; ok.textContent = T.ok;
      ok.onclick = () => location.reload();
      $('peopleError').append(ok);
      return;
    }
    $('peopleError').textContent = await failText(r);
  });
  function genPw() {
    const abc = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
    const v = crypto.getRandomValues(new Uint32Array(12));
    return [...v].map(n => abc[n % abc.length]).join('');
  }
  if ($('genPw')) $('genPw').onclick = () => { $('inviteForm').password.value = genPw(); };
  if ($('pwDialog')) {
    let pwEmail = '';
    $('pwDialog').addEventListener('close', () => { if ($('pwSet').disabled) location.reload(); });
    $('pwGen').onclick = () => { $('pwNew').value = genPw(); };
    $('pwClose').onclick = () => $('pwDialog').close();
    document.querySelectorAll('.setpw').forEach(b => b.onclick = () => {
      pwEmail = b.dataset.email;
      $('pwWho').textContent = pwEmail;
      $('pwNew').value = ''; $('pwNew').disabled = false; $('pwSet').disabled = false;
      $('pwMsg').textContent = ''; $('pwError').textContent = '';
      $('pwDialog').showModal();
    });
    $('pwForm').addEventListener('submit', async e => {
      e.preventDefault();
      const r = await reach(postJson('/api/people/password', { email: pwEmail, password: $('pwNew').value }));
      if (!r.ok) { $('pwError').textContent = await failText(r); return; }
      $('pwError').textContent = '';
      $('pwMsg').textContent = T.pwSet;
      $('pwSet').disabled = true; $('pwNew').disabled = true;  // the dialog reloads the page when closed
    });
  }
  document.querySelectorAll('.lockreset').forEach(b => b.onclick = async () => {
    if (!confirm(fmt(T.confirmLockReset, { email: b.dataset.email }))) return;
    const r = await reach(postJson('/api/people/lock-reset', { email: b.dataset.email }));
    if (!r.ok) { $('peopleError').textContent = await failText(r); return; }
    $('peopleError').textContent = '';
    $('codeWho').textContent = b.dataset.email;
    $('codeShown').textContent = (await r.json()).code;
    $('codeDialog').showModal();
  });
  $('codeClose').onclick = () => $('codeDialog').close();
  $('codeDialog').addEventListener('close', () => location.reload());  // the row is current again
  document.querySelectorAll('.unperson').forEach(b => b.onclick = async () => {
    if (!confirm(fmt(T.confirmRemove, { email: b.dataset.email }))) return;
    const r = await reach(postJson('/api/people/remove', { email: b.dataset.email }));
    if (r.ok) return location.reload();
    $('peopleError').textContent = await failText(r);
  });
})();
