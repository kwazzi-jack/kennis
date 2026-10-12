// Draw one operation while it runs, from the events the server pushes.
//
// **Every word arrives already written.** The server sends a `text`
// per message, chosen in Python by `render/`, so this appends and
// positions and never composes a sentence. A script that built "3 of
// 12" out of two numbers would be a second place the interface's
// words live. The clock is the same: the server sends "41s".
//
// **A push, not a poll.** `EventSource` holds one connection that the
// server writes to and closes when the operation ends. Nothing here
// runs on a timer.
//
// **Every panel, not the first.** A job's own page and the strip both
// draw one for the same job, and a page drawn while a job runs carries
// it in the strip. Each panel holds its own connection.
(function () {
  document.querySelectorAll(".job[data-job]").forEach(watch);

  function watch(panel) {
    if (panel.dataset.watching) { return; }
    panel.dataset.watching = "yes";

    var id = panel.dataset.job;
    var bar = panel.querySelector(".job-bar");
    var count = panel.querySelector(".job-count");
    var step = panel.querySelector(".job-step");
    var clock = panel.querySelector(".job-clock");
    var lines = panel.querySelector(".job-lines");
    var outcome = panel.querySelector(".job-outcome");
    var source = new EventSource("/job/" + id + "/events");

    function addLine(message) {
      var item = document.createElement("li");
      if (message.marker) {
        var marker = document.createElement("span");
        marker.className = "marker";
        marker.textContent = message.marker;
        item.appendChild(marker);
        item.appendChild(document.createTextNode(" "));
      }
      item.appendChild(document.createTextNode(message.text));
      if (message.detail) {
        var detail = document.createElement("span");
        detail.className = "role-muted";
        detail.textContent = " - " + message.detail;
        item.appendChild(detail);
      }
      if (message.outcome) { item.className = "role-" + message.outcome; }
      if (message.severity) { item.className = "role-" + message.severity; }
      lines.appendChild(item);
    }

    // A part of the page the outcome changed - a backup's section - is
    // asked for again, where this page has one. In code rather than as
    // an `hx-trigger` filter, because htmx 2.0.4 never fires `load`
    // with a filter (measured: `load[...]` sent nothing, `load` did).
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

    function finish() {
      source.close();
      bar.hidden = true;
      step.textContent = "";
      clock.textContent = "";
      // Fetched rather than streamed: the outcome is a page of markup
      // with forms in it, and building that in a script would put the
      // repair buttons somewhere other than where every other word on
      // this interface is decided.
      fetch("/job/" + id + "/outcome", { credentials: "same-origin" })
        .then(function (answer) { return answer.text(); })
        .then(function (html) {
          outcome.innerHTML = html;
          // The outcome is the record and the live lines were progress:
          // an outcome that lists its items replaces them, or a finished
          // sync lists every document twice.
          if (outcome.querySelector(".items")) {
            lines.remove();
          }
          if (window.htmx) { window.htmx.process(outcome); }
          redraw(outcome);
        })
        .catch(function () {
          // The operation still happened; only this page's account of
          // it is missing, and saying nothing is better than claiming
          // a failure that did not occur.
        });
    }

    source.onmessage = function (event) {
      var message = JSON.parse(event.data);
      if (message.kind === "closed") { finish(); return; }
      if (message.kind === "current") { step.textContent = message.text; return; }
      if (message.kind === "elapsed") { clock.textContent = message.text; return; }
      if (message.kind === "progress") {
        bar.hidden = false;
        if (message.total) {
          bar.max = message.total;
          bar.value = message.completed;
        } else {
          bar.removeAttribute("value");
        }
        count.textContent = message.text;
        return;
      }
      if (message.kind === "finished") { return; }
      addLine(message);
    };

    source.onerror = function () {
      // A dropped connection is not a failed operation, and the work
      // carries on without this page. Ask for the outcome once: if it
      // is ready the reader sees it, and if it is not they are told so
      // rather than left watching a bar that will never move.
      finish();
    };
  }
})();
