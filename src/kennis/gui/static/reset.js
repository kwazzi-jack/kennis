// Show each setting's reset button (#666).
//
// The button asks the server, through htmx, to redraw the section with its
// setting at the default; nothing is written until Save. Without htmx it
// would do nothing, so the server draws it hidden and this shows it, on the
// page and on every section htmx swaps in. Nothing here composes a word.
(function () {
  function show(root) {
    if (!window.htmx || !root.querySelectorAll) { return; }
    root.querySelectorAll(".setting-reset[hidden]").forEach(function (button) {
      button.hidden = false;
    });
  }

  show(document);
  document.body.addEventListener("htmx:afterSwap", function (event) {
    show((event.detail && event.detail.target) || document);
  });
})();
