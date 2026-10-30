// Settings, account section (templates/settings.html): delete my data. The dialog asks for the code, or for a typed word
// when there is no code. The page stays, with a line saying it is done.
(function () {
  const card = document.getElementById("accountCard");
  const ask = document.getElementById("deleteAsk");
  const form = document.getElementById("deleteForm");
  const err = document.getElementById("deleteError");
  const done = document.getElementById("deleteDone");
  const field = form.querySelector("input");

  document.getElementById("deleteData").addEventListener("click", () => {
    err.textContent = "";
    done.textContent = "";
    field.value = "";
    ask.showModal();
  });
  document.getElementById("deleteCancel").addEventListener("click", () => ask.close());
  if (field.classList.contains("code")) {
    field.addEventListener("input", () => { field.value = field.value.replace(/[^0-9]/g, ""); });
  }

  // A code costs an attempt, so one at a time
  let busy = false;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    busy = true;
    const r = await window.hubPost("/api/me/delete-data", { [field.name]: field.value });
    busy = false;
    if (r.ok) {
      ask.close();
      done.textContent = card.dataset.done;
      return;
    }
    err.textContent = r.detail || card.dataset.failed;
    field.value = "";
    field.focus();
  });
})();
