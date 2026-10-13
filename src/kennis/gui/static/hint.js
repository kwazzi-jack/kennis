// Keep the search box's placeholder naming the scope the select is
// pointed at.
//
// **Every word arrives already written.** The server puts the
// sentence for each scope on that scope's `<option>` as `data-hint`,
// and this copies the selected one onto the input. Nothing here
// composes a sentence, and a test asserts that - the moment this
// file contains "Search", the interface has two places its words
// live and only one of them is tested. The same rule `progress.js`
// follows.
//
// The first paint is the server's too, because the scope arrives in
// the address and the page has to be right before any script runs.
// This only handles the change afterwards.
(function () {
  var box = document.querySelector("input[name=q]");
  var where = document.querySelector("select[name=scope]");
  if (!box || !where) { return; }

  function follow() {
    var chosen = where.options[where.selectedIndex];
    if (chosen && chosen.dataset.hint) { box.placeholder = chosen.dataset.hint; }
  }

  where.addEventListener("change", follow);

  // `/` reaches the box from anywhere on the page, as the key drawn
  // inside it says - except where `/` is something being typed.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) { return; }
    var here = document.activeElement;
    // The box itself, empty: it is focused on arrival, so the key that
    // means "go to the search" was typed into it as the query's first
    // character. No query begins with one.
    if (here === box && box.value === "") { event.preventDefault(); return; }
    if (here && (here.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(here.tagName))) { return; }
    event.preventDefault();
    box.focus();
    box.select();
  });
})();
