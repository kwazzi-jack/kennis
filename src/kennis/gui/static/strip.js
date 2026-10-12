// Collapse the activity strip to its first line, and remember it.
//
// The state is a cookie the server draws onto `<html>` as `data-strip`,
// as `pane.js` does for the pane; this script only handles the click.
// Both labels arrive from the server on the button.
(function () {
  var toggle = document.getElementById("strip-toggle");
  if (!toggle) { return; }
  var root = document.documentElement;
  var YEAR = 31536000;

  toggle.addEventListener("click", function () {
    var closing = root.dataset.strip !== "closed";
    var state = closing ? "closed" : "open";
    var label = closing ? toggle.dataset.show : toggle.dataset.hide;
    root.dataset.strip = state;
    toggle.setAttribute("aria-expanded", closing ? "false" : "true");
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("title", label);
    document.cookie =
      "strip=" + state + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();
