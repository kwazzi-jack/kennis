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

  // `toggle` does not bubble, so it is caught on the way down.
  pane.addEventListener("toggle", function (event) {
    var menu = event.target;
    if (menu.matches && menu.matches("details.menu") && menu.open) { closeAll(menu); }
  }, true);

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
