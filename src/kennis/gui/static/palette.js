// The palette (11g): filter as it is typed, Up and Down wrapping over
// what is visible, the selection kept in view, Enter runs it. And Ctrl K
// (Cmd K) opens it, by clicking the bar's own link to it, so the key
// and the button are one route.
//
// The server draws every entry, lower-cases what each is matched on and
// writes the "nothing matches" sentence; this file compares, hides,
// moves and clicks. Nothing here composes a sentence.
(function () {
  var TYPED_SHOWN = 30;

  document.addEventListener("keydown", function (event) {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") { return; }
    var open = document.querySelector(".palette-open");
    if (!open) { return; }
    event.preventDefault();
    open.click();
  });

  function options(palette) {
    return Array.prototype.slice.call(palette.querySelectorAll("[role=option]"));
  }

  function shown(palette) {
    return options(palette).filter(function (option) { return !option.hidden; });
  }

  function select(palette, option) {
    var input = palette.querySelector(".palette-input");
    options(palette).forEach(function (each) {
      each.setAttribute("aria-selected", each === option ? "true" : "false");
    });
    if (option) {
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function selected(palette) {
    return palette.querySelector("[role=option][aria-selected=true]");
  }

  document.addEventListener("input", function (event) {
    var palette = event.target.closest(".palette");
    if (!palette || !event.target.matches(".palette-input")) { return; }
    var needle = event.target.value.trim().toLowerCase();
    // A document or a past search shows only for something typed, and
    // only the first few that match: the corpus may hold thousands.
    var typed = 0;
    options(palette).forEach(function (option) {
      var matches = option.dataset.match.indexOf(needle) !== -1;
      if (option.hasAttribute("data-typed")) {
        matches = matches && needle !== "" && typed < TYPED_SHOWN;
        if (matches) { typed += 1; }
      }
      option.hidden = !matches;
    });
    var visible = shown(palette);
    palette.querySelector(".palette-empty").hidden = visible.length > 0;
    select(palette, visible[0] || null);
  });

  document.addEventListener("keydown", function (event) {
    var palette = event.target.closest && event.target.closest(".palette");
    if (!palette || !event.target.matches(".palette-input")) { return; }
    var visible = shown(palette);
    if (!visible.length) { return; }
    var at = visible.indexOf(selected(palette));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      var step = event.key === "ArrowDown" ? 1 : -1;
      select(palette, visible[(at + step + visible.length) % visible.length]);
    } else if (event.key === "Enter") {
      event.preventDefault();
      var link = (visible[at] || visible[0]).querySelector("a");
      if (link) { link.click(); }
    }
  });

  // A pointer chooses as well: hovering moves the selection, so Enter
  // after a hover runs what is under the pointer.
  document.addEventListener("mousemove", function (event) {
    var option = event.target.closest && event.target.closest(".palette [role=option]");
    if (option && option.getAttribute("aria-selected") !== "true") {
      select(option.closest(".palette"), option);
    }
  });
})();
