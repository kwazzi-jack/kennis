// Place an info tip beside the button that opened it.
//
// The tip is the browser's own popover and opens and closes without this;
// a browser that cannot anchor it to its button centres it on the page,
// so this moves it under the button, kept inside the window. Nothing here
// composes words.
(function () {
  var GAP = 6;

  document.addEventListener("toggle", function (event) {
    var tip = event.target;
    if (!tip.classList || !tip.classList.contains("tip") || event.newState !== "open") {
      return;
    }
    var button = document.querySelector('[popovertarget="' + tip.id + '"]');
    if (!button) { return; }
    var from = button.getBoundingClientRect();
    tip.style.margin = "0";
    tip.style.position = "fixed";
    var width = tip.offsetWidth;
    var left = Math.min(Math.max(GAP, from.left), window.innerWidth - width - GAP);
    var below = from.bottom + GAP;
    var top = below + tip.offsetHeight > window.innerHeight - GAP
      ? Math.max(GAP, from.top - tip.offsetHeight - GAP)
      : below;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }, true);
})();
