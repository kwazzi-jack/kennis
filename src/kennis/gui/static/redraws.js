// Ask again for each part of the page an answer says it changed.
//
// An answer names a part by a hidden hook - `data-redraw-id`, the element,
// and `data-redraw-route`, where it is drawn - and the part is asked for
// only where this page has it. That guard is what keeps a collection's
// branch that was never opened from being fetched, and it is never left
// out: `htmx.ajax` with no target swaps into the body, which replaced a
// page that had no such section, strip and all.
//
// Two kinds of answer carry hooks. A job's outcome is fetched by
// `progress.js`, which calls `kennisRedraw` itself; a note's answer is
// swapped in by htmx, and is read here. Loaded once, by the page: a job's
// panel loads `progress.js` again each time it is drawn, so a listener
// added there would be added once per job.
(function () {
  // In code rather than as an `hx-trigger` filter, because htmx 2.0.4
  // never fires `load` with a filter (measured: `load[...]` sent nothing,
  // `load` did).
  function redraw(within) {
    var hooks = within.querySelectorAll("[data-redraw-id]");
    Array.prototype.forEach.call(hooks, function (hook) {
      var target = document.getElementById(hook.dataset.redrawId);
      if (!target || !window.htmx) { return; }
      window.htmx.ajax("GET", hook.dataset.redrawRoute, {
        target: target,
        swap: "outerHTML",
      });
    });
  }

  window.kennisRedraw = redraw;

  // A job handed back open - refused before it began, or the running one
  // answering a second request - shows its panel: the answer is to the
  // reader's own action. The server marks it; nothing here decides.
  function open(within) {
    var panels = within.querySelectorAll(".job[data-open] [popover]");
    Array.prototype.forEach.call(panels, function (panel) {
      if (panel.showPopover && !panel.matches(":popover-open")) {
        panel.showPopover();
      }
    });
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    var swapped = event.detail && event.detail.target;
    if (swapped && swapped.querySelectorAll) {
      redraw(swapped);
      open(swapped);
    }
  });
})();
