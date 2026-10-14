// Show and hide a document's inspector, and remember which.
//
// The pane's rule (`pane.js`): the state is a cookie the server draws
// onto `<html data-inspector>`, so the first paint is already right,
// and this script only handles the click. `path=/` because every
// document page shares the choice, `samesite=strict` as the token
// cookie has it.
//
// Both labels arrive from the server on the button. Nothing here
// composes a sentence, and a test asserts that.
(function () {
  var toggle = document.getElementById("inspector-toggle");
  if (!toggle) { return; }
  var root = document.documentElement;
  var YEAR = 31536000;

  toggle.addEventListener("click", function () {
    var closing = root.dataset.inspector !== "closed";
    var state = closing ? "closed" : "open";
    var label = closing ? toggle.dataset.show : toggle.dataset.hide;
    root.dataset.inspector = state;
    toggle.setAttribute("aria-expanded", closing ? "false" : "true");
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("title", label);
    document.cookie =
      "inspector=" + state + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();

// Copy a citekey. The button is drawn hidden, because without a script it
// could do nothing and the value beside it is already selectable text; it
// appears only where the clipboard can be reached. Both its words arrive
// from the server.
(function () {
  if (!navigator.clipboard) { return; }
  document.querySelectorAll("button.copy[data-copy]").forEach(function (button) {
    button.hidden = false;
    var label = button.textContent;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(button.dataset.copy).then(function () {
        button.textContent = button.dataset.copied;
        setTimeout(function () { button.textContent = label; }, 1500);
      });
    });
  });
})();
