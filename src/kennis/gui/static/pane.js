// Open and close the pane, and remember which.
//
// **The state is a cookie, and the server renders it.** This script
// only handles the click; the first paint of every page is already
// correct, because the cookie was on the request. Reading
// `localStorage` after paint would show the pane open and then
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
  var toggle = document.getElementById("pane-toggle");
  if (!toggle) { return; }
  var root = document.documentElement;
  var YEAR = 31536000;

  // **Narrow, the pane is a drawer**, opened over the page and closed
  // again by the same button, Escape, or a click outside it. Not
  // remembered: the wide layout's choice is the cookie's, and a drawer
  // left open would cover the page on the next one.
  var narrow = window.matchMedia("(max-width: 46rem)");
  var pane = document.querySelector(".pane");

  function label(open) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? toggle.dataset.hide : toggle.dataset.show);
  }

  function drawer(open) {
    root.dataset.drawer = open ? "open" : "closed";
    label(open);
  }

  if (narrow.matches) { drawer(false); }
  narrow.addEventListener("change", function () {
    if (narrow.matches) { drawer(false); return; }
    delete root.dataset.drawer;
    label(root.dataset.pane !== "closed");
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || root.dataset.drawer !== "open") { return; }
    drawer(false);
    toggle.focus();
  });
  document.addEventListener("click", function (event) {
    if (root.dataset.drawer !== "open") { return; }
    if (toggle.contains(event.target) || (pane && pane.contains(event.target))) { return; }
    drawer(false);
  });

  toggle.addEventListener("click", function () {
    if (narrow.matches) {
      drawer(root.dataset.drawer !== "open");
      if (root.dataset.drawer === "open" && pane) {
        var first = pane.querySelector("a, summary");
        if (first) { first.focus(); }
      }
      return;
    }
    var closing = root.dataset.pane !== "closed";
    var state = closing ? "closed" : "open";
    root.dataset.pane = state;
    toggle.setAttribute("aria-expanded", closing ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      closing ? toggle.dataset.show : toggle.dataset.hide
    );
    document.cookie =
      "pane=" + state + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();
