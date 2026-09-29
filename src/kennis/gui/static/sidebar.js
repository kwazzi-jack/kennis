// Open and close the sidebar, and remember which.
//
// **The state is a cookie, and the server renders it.** This script
// only handles the click; the first paint of every page is already
// correct, because the cookie was on the request. Reading
// `localStorage` after paint would show the sidebar open and then
// collapse it on every page load.
//
// Written here rather than by a round trip, so the attributes are
// this file's responsibility: `path=/` so it is not scoped to
// whichever page happened to set it, and `samesite=strict` for the
// same reason the token cookie has it.
//
// Both labels arrive from the server on the button. Nothing here
// composes a sentence, and a test asserts that.
(function () {
  var toggle = document.getElementById("sidebar-toggle");
  if (!toggle) { return; }
  var root = document.documentElement;
  var YEAR = 31536000;

  toggle.addEventListener("click", function () {
    var closing = root.dataset.sidebar !== "closed";
    var state = closing ? "closed" : "open";
    root.dataset.sidebar = state;
    toggle.setAttribute("aria-expanded", closing ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      closing ? toggle.dataset.show : toggle.dataset.hide
    );
    document.cookie =
      "sidebar=" + state + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();
