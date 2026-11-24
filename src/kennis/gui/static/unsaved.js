// Disable Save while no field differs from what is saved (Brian,
// 2026-11-24): an enabled Save is what says the tab has unsaved changes.
//
// The server marks each setting's field with `data-saved`, the value in
// force, and never draws Save disabled, so without this script the page
// still saves. A box is compared by whether it is ticked, a number as a
// number (3 is 3.0), anything else as its text. A disabled field is set by
// the environment and cannot change. Nothing here composes a word.
(function () {
  function differs(field) {
    var saved = field.dataset.saved;
    if (field.type === "checkbox") {
      return (field.checked ? "true" : "false") !== saved;
    }
    if (field.type === "number" && field.value !== "" && saved !== "") {
      return Number(field.value) !== Number(saved);
    }
    return field.value !== saved;
  }

  function update(form) {
    var save = form.querySelector(".save-bar button[type=submit]");
    if (!save) { return; }
    var fields = form.querySelectorAll("[data-saved]:not(:disabled)");
    save.disabled = !Array.prototype.some.call(fields, differs);
  }

  function updateAll() {
    document.querySelectorAll("form.kennis-settings").forEach(update);
  }

  function onEdit(event) {
    var form = event.target.closest && event.target.closest("form.kennis-settings");
    if (form) { update(form); }
  }

  document.addEventListener("input", onEdit);
  document.addEventListener("change", onEdit);
  document.body.addEventListener("htmx:afterSettle", updateAll);
  updateAll();
})();
