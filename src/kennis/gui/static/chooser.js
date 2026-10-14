// Write a chosen path into the field the chooser was opened for.
//
// The server lists one folder of the computer kennis runs on into a
// `.chooser` beside the field; a folder opens in place by htmx, and a
// file - or the folder itself, where a field takes one - carries its
// whole path in `data-choose`. This copies it into the field named by
// the panel's `data-target`: replacing an input's value, or adding a
// line to a textarea, which holds one path per line. It then sends an
// `input` event so the preview or the line check runs as if typed.
//
// Nothing here composes a sentence; every word is the server's.
(function () {
  document.body.addEventListener("click", function (event) {
    var chosen = event.target.closest("[data-choose]");
    var cancel = event.target.closest("[data-chooser-cancel]");
    if (!chosen && !cancel) { return; }
    var panel = event.target.closest(".chooser-panel");
    var slot = panel && panel.closest(".chooser");
    if (!slot) { return; }
    var form = slot.closest("form");
    var field = form && form.querySelector('[name="' + panel.dataset.target + '"]');
    if (chosen && field) {
      var path = chosen.dataset.choose;
      if (field.tagName === "TEXTAREA") {
        var kept = field.value.replace(/\s+$/, "");
        field.value = kept ? kept + "\n" + path : path;
      } else {
        field.value = path;
      }
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.focus();
    }
    slot.innerHTML = "";
  });
})();
