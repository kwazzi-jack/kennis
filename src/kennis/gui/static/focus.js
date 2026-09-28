// Put the cursor in the search box on arrival.
//
// `autofocus` alone does not do it here: the attribute is honoured
// while the document parses, and htmx's own boot runs after, so the
// element ends up present and unfocused. Measured, not assumed -
// `document.activeElement` was `body` on every load.
//
// Only when nothing else has focus, so a reader who clicked into the
// scope select before this ran is not yanked out of it. And only when
// the box is empty, because a page restored by the Back button
// already has a query in it and moving the caret there would be the
// browser undoing the reader's place.
(function () {
  var box = document.querySelector('input[name=q]');
  if (!box) return;
  var idle = document.activeElement === document.body ||
             document.activeElement === null;
  if (idle && !box.value) box.focus();
})();
