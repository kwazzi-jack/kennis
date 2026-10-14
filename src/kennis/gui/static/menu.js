// The tree's menus: right-click opens one, Escape and a click elsewhere
// close it, and only one is open at a time.
//
// Each menu is a `<details>` whose summary is a visible button, so it
// opens from the keyboard and by a click with no script at all, and
// every entry is a link or a form. This file only adds what a
// `<details>` cannot do on its own. Nothing here composes a sentence.
(function () {
  var pane = document.querySelector(".pane");
  if (!pane) { return; }

  function closeAll(except) {
    pane.querySelectorAll("details.menu[open]").forEach(function (menu) {
      if (menu !== except) { menu.open = false; }
    });
  }

  // A row's menu is its own child, a sibling of the link it acts on.
  function menuOf(target) {
    var row = target.closest("li.row, li.group");
    return row ? row.querySelector(":scope > details.menu") : null;
  }

  pane.addEventListener("contextmenu", function (event) {
    var menu = menuOf(event.target);
    if (!menu) { return; }
    event.preventDefault();
    closeAll(menu);
    menu.open = true;
    var first = menu.querySelector(".item");
    if (first) { first.focus(); }
  });

  // **Placed against the window, not the pane.** The pane scrolls, so
  // it clips what overflows it, and a menu anchored to a row near its
  // edge was cut off mid-word ("pen", "ove to group"). Fixed to the
  // button's position and kept inside the window; without a script it
  // stays where the stylesheet puts it, which still opens.
  function place(menu) {
    var items = menu.querySelector(".menu-items");
    var button = menu.querySelector("summary");
    if (!items || !button) { return; }
    var at = button.getBoundingClientRect();
    items.style.position = "fixed";
    items.style.right = "auto";
    items.style.top = at.bottom + "px";
    var width = items.offsetWidth;
    var left = Math.min(at.right - width, window.innerWidth - width - 8);
    items.style.left = Math.max(8, left) + "px";
  }

  // `toggle` does not bubble, so it is caught on the way down.
  pane.addEventListener("toggle", function (event) {
    var menu = event.target;
    if (menu.matches && menu.matches("details.menu") && menu.open) {
      closeAll(menu);
      place(menu);
    }
  }, true);

  // A fixed menu would stay put while its row scrolled away.
  pane.addEventListener("scroll", function () { closeAll(null); });

  // Closed once focus leaves it, so it never covers whatever the
  // keyboard moved on to (the accessibility review, finding 8).
  pane.addEventListener("focusout", function (event) {
    var menu = event.target.closest && event.target.closest("details.menu");
    if (!menu || !menu.open) { return; }
    // Only when focus went somewhere: a browser that does not focus a
    // clicked button reports nowhere, and closing then would take the
    // item away before its click lands. A click is handled below.
    if (!event.relatedTarget || menu.contains(event.relatedTarget)) { return; }
    menu.open = false;
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") { return; }
    var open = pane.querySelector("details.menu[open]");
    if (!open) { return; }
    open.open = false;
    open.querySelector("summary").focus();
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest("details.menu")) { closeAll(null); }
  });
})();
