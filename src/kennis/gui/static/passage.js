// Close each hit's passage to its window, and open it in place.
//
// The server draws every passage whole, as three parts - before, the
// window, after - and this adds `closed`, which the stylesheet uses to
// hide the two outer parts and show an ellipsis where they were. So a
// reader without a script reads every passage whole, and no text is
// ever on the page twice (#415).
//
// **Every word arrives already written.** The toggle's two labels are
// its `data-open` and `data-close`; nothing here composes a sentence,
// and a test asserts that. The same rule `hint.js` and `progress.js`
// follow.
(function () {
  var still = window.matchMedia("(prefers-reduced-motion: reduce)");

  // The height moves rather than jumps, so the reader sees the text
  // arrive around the window instead of the list lurching under them.
  function resized(passage, change) {
    var from = passage.offsetHeight;
    change();
    var to = passage.offsetHeight;
    if (still.matches || from === to || !passage.animate) { return; }
    passage.style.overflow = "hidden";
    var motion = passage.animate(
      [{ height: from + "px" }, { height: to + "px" }],
      { duration: 180, easing: "ease-out" }
    );
    motion.onfinish = function () { passage.style.overflow = ""; };
  }

  function show(toggle, open) {
    var passage = toggle.closest(".hit").querySelector(".passage");
    resized(passage, function () { passage.classList.toggle("closed", !open); });
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.querySelector(".label").textContent =
      open ? toggle.dataset.close : toggle.dataset.open;
  }

  function prepare(root) {
    root.querySelectorAll(".hit .toggle[hidden]").forEach(function (toggle) {
      toggle.closest(".hit").querySelector(".passage").classList.add("closed");
      toggle.hidden = false;
      toggle.addEventListener("click", function () {
        var opening = toggle.getAttribute("aria-expanded") !== "true";
        // One open at a time: a second opened passage would push the
        // first out of view, and the reader would be reading neither.
        if (opening) {
          document.querySelectorAll('.hit .toggle[aria-expanded="true"]')
            .forEach(function (other) { show(other, false); });
        }
        show(toggle, opening);
      });
    });
  }

  prepare(document);
  document.body.addEventListener("htmx:afterSettle", function (event) {
    prepare(event.target);
  });
})();
