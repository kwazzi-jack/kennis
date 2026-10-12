// Drag, or step by the keyboard, the size a handle names, and remember
// it (`gui/layout.py`).
//
// **The size is a cookie, and the server draws it** onto `<html>`, so
// this script only answers the pointer and the keys; every page's first
// paint is already the size the reader left. Its name is the cookie and
// the custom property at once.
//
// Each handle says what it sizes (`data-target`), which way the pointer
// moves to make it larger (`data-grow`) and its bounds in pixels
// (`aria-valuemin`, `aria-valuemax`). Nothing here composes a word.
(function () {
  var root = document.documentElement;
  var YEAR = 31536000;
  var STEP = 16;

  document.querySelectorAll("[data-resize]").forEach(function (handle) {
    var name = handle.dataset.resize;
    var target = document.querySelector(handle.dataset.target);
    if (!target) { return; }
    var grow = handle.dataset.grow;
    var least = Number(handle.getAttribute("aria-valuemin"));
    var most = Number(handle.getAttribute("aria-valuemax"));
    var across = grow === "left" || grow === "right";

    function current() {
      var box = target.getBoundingClientRect();
      return Math.round(across ? box.width : box.height);
    }

    function set(size) {
      var clamped = Math.min(most, Math.max(least, Math.round(size)));
      root.style.setProperty("--" + name, clamped + "px");
      handle.setAttribute("aria-valuenow", String(clamped));
      return clamped;
    }

    function remember(size) {
      document.cookie =
        name + "=" + size + "; path=/; max-age=" + YEAR + "; samesite=strict";
    }

    // Back to the layout's own default: the property and the cookie go.
    function reset() {
      root.style.removeProperty("--" + name);
      document.cookie = name + "=; path=/; max-age=0; samesite=strict";
      handle.setAttribute("aria-valuenow", String(current()));
    }

    // From the pointer to the far edge of what is being sized.
    function sizeAt(event) {
      var box = target.getBoundingClientRect();
      if (grow === "right") { return event.clientX - box.left; }
      if (grow === "left") { return box.right - event.clientX; }
      return box.bottom - event.clientY;
    }

    handle.setAttribute("aria-valuenow", String(current()));

    handle.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) { return; }
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      root.classList.add("resizing");
      var last = current();

      function move(moved) { last = set(sizeAt(moved)); }
      function release() {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", release);
        handle.removeEventListener("pointercancel", release);
        root.classList.remove("resizing");
        remember(last);
      }
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", release);
      handle.addEventListener("pointercancel", release);
    });

    handle.addEventListener("dblclick", reset);

    handle.addEventListener("keydown", function (event) {
      var larger = { right: "ArrowRight", left: "ArrowLeft", up: "ArrowUp" }[grow];
      var smaller = { right: "ArrowLeft", left: "ArrowRight", up: "ArrowDown" }[grow];
      if (event.key === "Home") {
        event.preventDefault();
        reset();
        return;
      }
      if (event.key !== larger && event.key !== smaller) { return; }
      event.preventDefault();
      // From the size last set, not the one measured: the pane's width
      // transitions, so a second press would read it halfway there.
      var from = Number(handle.getAttribute("aria-valuenow")) || current();
      remember(set(from + (event.key === larger ? STEP : -STEP)));
    });
  });
})();
