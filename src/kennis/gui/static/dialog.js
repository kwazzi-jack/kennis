// Open an action's dialog when it arrives, and close it when its form
// has been sent.
//
// The bar's actions are links that htmx fetches into `#dialog`. A
// `<dialog>` element arriving there is shown as a modal, which gives
// it focus, keeps the page behind it inert, and closes on Escape with
// no code here. Without a script the link is followed instead and the
// form arrives as a page, so nothing in this file is needed to reach
// any action.
//
// A form marked `data-closes-dialog` hands its answer to `#job` in the
// strip, so once it has been sent the dialog has nothing left to show.
// The remember form is not marked: it answers inside the dialog.
//
// Nothing here composes a sentence.
(function () {
  var slot = document.getElementById("dialog");
  if (!slot) { return; }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target !== slot) { return; }
    var dialog = slot.querySelector("dialog");
    if (dialog && !dialog.open) { dialog.showModal(); }
  });

  // A dialog that is closed - by Escape, by its close button, or after
  // its form was sent - is removed, so the next action fetches a fresh
  // form rather than finding the last one half filled in.
  slot.addEventListener("close", function (event) {
    if (event.target.tagName === "DIALOG") { event.target.remove(); }
  }, true);

  // Cancel is a link, so a page without a script can leave; inside a
  // dialog it closes the dialog instead of being followed.
  slot.addEventListener("click", function (event) {
    var close = event.target.closest("[data-close]");
    if (!close) { return; }
    event.preventDefault();
    close.closest("dialog").close();
  });

  // Only the form's own POST closes it. A control inside the form - a
  // preview, Browse, Another group - makes GET requests of its own, and
  // htmx can report one of those against the form; closing on it shut
  // the Add dialog under the reader's hands (11d).
  document.body.addEventListener("htmx:afterRequest", function (event) {
    var form = event.detail.elt;
    if (event.detail.requestConfig.verb !== "post") { return; }
    if (!form.matches || !form.matches("form[data-closes-dialog]")) { return; }
    var dialog = form.closest("dialog");
    if (dialog && event.detail.successful) { dialog.close(); }
  });

  // Keep the Add form's destination in step with its fields. Each part
  // names its field, and this copies the value across: it composes no
  // words, as `hint.js` copies the scope's hint.
  function mirror(form) {
    form.querySelectorAll("[data-mirror]").forEach(function (part) {
      var field = form.elements[part.dataset.mirror];
      part.textContent = field ? field.value.trim() : "";
    });
  }
  ["input", "change"].forEach(function (kind) {
    document.addEventListener(kind, function (event) {
      var form = event.target.form;
      if (form && form.querySelector("[data-mirror]")) { mirror(form); }
    });
  });
})();
