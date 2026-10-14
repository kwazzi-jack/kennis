// Bring the reader's first marked word into a closed passage.
//
// The server parts a passage at the first top-level block holding a
// mark, so the fade usually starts on the reader's words already. A
// table is one block, though, and a mark in its twentieth row sat
// under the fade while the head of the table showed. This moves the
// clipped body - `overflow: hidden` still scrolls by assignment - so
// the mark sits a third of the way down, and says so with
// `data-shifted`, which the stylesheet reads to fade the top as well.
//
// Opening needs nothing from here: as the body grows the browser
// clamps `scrollTop` to zero, so the whole passage is shown from its
// start. Closing puts the shift back. Without this script a closed
// passage shows its first lines, which is what it showed before.
//
// It measures and composes no words.
(function () {
  function settle(root) {
    root.querySelectorAll(".passage.clamped .body").forEach(function (body) {
      var passage = body.closest(".passage");
      if (passage.querySelector("details[open]")) { return; }
      var mark = body.querySelector("mark");
      var shift = 0;
      if (mark) {
        var below = mark.getBoundingClientRect().top
          - body.getBoundingClientRect().top + body.scrollTop;
        shift = Math.max(0, below - body.clientHeight / 3);
      }
      body.scrollTop = shift;
      if (body.scrollTop > 0) {
        body.dataset.shifted = "yes";
      } else {
        delete body.dataset.shifted;
      }
    });
  }

  settle(document);
  // After KaTeX has typeset, since an equation changes the heights.
  window.addEventListener("load", function () { settle(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) {
    settle(event.target);
  });
  // `toggle` does not bubble, so it is heard in the capture phase. It
  // fires as a passage starts to close, while the body is still its
  // open height, so the shift is measured again once the height has
  // finished moving; with reduced motion there is no transition and
  // the first measurement is the one that counts.
  document.addEventListener("toggle", function (event) {
    var passage = event.target.closest(".passage");
    if (passage && !event.target.open) { settle(passage); }
  }, true);
  document.addEventListener("transitionend", function (event) {
    if (event.propertyName !== "max-height") { return; }
    var passage = event.target.closest(".passage.clamped");
    if (passage) { settle(passage); }
  });
})();
