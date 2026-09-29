// Choose the palette: the system's, light, or dark.
//
// **The server renders the choice and this only handles the
// change.** The cookie is on the request, so `<html data-theme>` is
// right in the first byte. Read from `localStorage` after paint,
// every page would render in the system's colours and then repaint
// into the chosen ones - a flash of the wrong palette on every
// single load, which is the one thing a theme control must not do.
//
// `system` sets the attribute too rather than removing it. The CSS
// matches only `light` and `dark`, so `system` falls through to the
// media query on its own, and writing it keeps the attribute and
// the control saying the same thing.
//
// The cookie's attributes are this file's responsibility, as in
// `sidebar.js`: `path=/` so it is not scoped to whichever page set
// it, and `samesite=strict` for the reason the token cookie has it.
(function () {
  var choice = document.getElementById("theme");
  if (!choice) { return; }
  var YEAR = 31536000;

  choice.addEventListener("change", function () {
    document.documentElement.dataset.theme = choice.value;
    document.cookie =
      "theme=" + choice.value + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();
