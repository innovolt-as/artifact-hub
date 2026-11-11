// The choice of collection names in the admin sheet (the add-only and the guest-readable collections). Pure functions
// with no DOM, so they can be tested alone; static/admin-apps.js draws the buttons.
window.AdminChips = (() => {
  // The rule of the server (APPEND_NAME_RE, and not "data")
  const valid = name => /^[A-Za-z0-9_-]{1,64}$/.test(name) && name !== 'data';

  // The buttons of one view, sorted: every existing collection and every selected name. A name the other setting has
  // is disabled, unless it is selected here (the server never lets that happen, so this only keeps the picture honest)
  function chips(existing, selected, other) {
    return [...new Set([...existing, ...selected])].sort().map(name => {
      const on = selected.includes(name);
      return { name, on, disabled: !on && other.includes(name) };
    });
  }

  // A press on a button: the name is added at the end, or taken out
  const press = (selected, name) => selected.includes(name) ? selected.filter(n => n !== name) : [...selected, name];

  // What was typed in the field: names separated by commas. Every valid one becomes selected; the others are refused
  // with the reason ('bad' for a name the server would not take, 'other' for one the other setting has)
  function typed(selected, text, other) {
    const out = [...selected], refused = [];
    for (const name of text.split(',').map(n => n.trim()).filter(Boolean)) {
      if (!valid(name)) refused.push({ name, why: 'bad' });
      else if (other.includes(name)) refused.push({ name, why: 'other' });
      else if (!out.includes(name)) out.push(name);
    }
    return { selected: out, refused };
  }

  return { chips, press, typed };
})();
