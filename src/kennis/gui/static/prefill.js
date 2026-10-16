// Keep a field the Paper preview filled in marked as kennis's only while
// it still holds what kennis put there.
//
// The server draws the mark: class `prefilled`, the value it filled in
// as `data-prefilled`, and a description for a screen reader. This only
// follows the reader's edits - the mark goes when the value changes and
// returns if it is typed back - and composes no words. Without a script
// the mark stays until the next preview, which is only cosmetic: the
// preview and the add compare the value with the hidden `prefilled-*`
// field, not with the mark.
(function () {
  document.addEventListener("input", function (event) {
    var field = event.target;
    if (!(field instanceof HTMLInputElement) || !field.hasAttribute("data-prefilled")) { return; }
    var still = field.value === field.getAttribute("data-prefilled");
    field.classList.toggle("prefilled", still);
    if (still) {
      field.setAttribute("aria-describedby", "add-prefilled-note");
    } else {
      field.removeAttribute("aria-describedby");
    }
  });
})();
