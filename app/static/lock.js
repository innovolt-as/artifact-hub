// The code screen (templates/lock.html). The fourth digit sends the form; without JavaScript the button does.
(() => {
  const form = document.querySelector('form[action^="/lock/"]');
  const field = form.querySelector('input.code[name="code"]');  // only on the first step
  // Each try costs an attempt, so the fourth digit plus Enter must not send the form twice
  let sent = false;
  form.addEventListener("submit", (e) => {
    if (sent) e.preventDefault();
    sent = true;
  });
  // Back to this page from the browser's page cache: it is a fresh try, and the old digits are gone
  addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    sent = false;
    form.reset();
  });
  if (field) {
    field.addEventListener("input", () => {
      if (/^[0-9]{4}$/.test(field.value)) form.querySelector("button").click();  // iOS 15 has no requestSubmit
    });
  }
})();
