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
// **What a screen reader hears is chosen, not everything that moves.**
// The strip was one live region holding a clock that ticked every
// second, so a reader heard the time over and over. Now one status
// region is told the step when it changes - at most every ten seconds -
// and the outcome's first sentence when it ends.
//
// **Every panel, not the first.** A job's own page and the strip both
// draw one for the same job, and a page drawn while a job runs carries
// it in the strip. Each panel holds its own connection. Only a running or
// queued job is watched: one that has ended arrives drawn by the server.
//
// **A value is shown in more than one place.** On the bar the job is a
// segment with its step and a thin bar; its panel has them again with
// the count, the clock and the lines. Each is written to every element
// of its class within the job.
(function () {
  document
    .querySelectorAll('.job[data-job][data-state="running"], .job[data-job][data-state="queued"]')
    .forEach(watch);

  function watch(panel) {
    if (panel.dataset.watching) { return; }
    panel.dataset.watching = "yes";

    var id = panel.dataset.job;
    var bars = panel.querySelectorAll(".job-bar");
    var lines = panel.querySelector(".job-lines");
    var outcome = panel.querySelector(".job-outcome");
    var source = new EventSource("/job/" + id + "/events");
    var status = document.getElementById("job-status");
    var said = 0;

    function setText(selector, text) {
      Array.prototype.forEach.call(panel.querySelectorAll(selector), function (node) {
        node.textContent = text;
      });
    }

    function announce(text, now) {
      if (!status || !text) { return; }
      var at = Date.now();
      if (!now && at - said < 10000) { return; }
      said = at;
      status.textContent = text;
    }

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
      if (message.kind === "item") { item.dataset.item = "yes"; }
      if (message.outcome) { item.className = "role-" + message.outcome; }
      if (message.severity) { item.className = "role-" + message.severity; }
      lines.appendChild(item);
    }

    function finish() {
      source.close();
      Array.prototype.forEach.call(bars, function (bar) { bar.hidden = true; });
      // "2093 of 2093" stayed on the line after the job had ended.
      setText(".job-count", "");
      // Fetched rather than streamed: the outcome is a page of markup
      // with forms in it, and building that in a script would put the
      // repair buttons somewhere other than where every other word on
      // this interface is decided.
      fetch("/job/" + id + "/outcome", { credentials: "same-origin" })
        .then(function (answer) {
          // A job that committed says which commit it left. htmx never
          // sees this request, so `revision.js` is told directly; without
          // it this window's own add was announced on the next focus as
          // a change from elsewhere.
          var written = answer.headers.get("X-Kennis-Revision");
          if (written) {
            document.body.dispatchEvent(new CustomEvent("kennis:written", {
              detail: { revision: written },
            }));
          }
          return answer.text();
        })
        .then(function (html) {
          outcome.innerHTML = html;
          // The headline goes on the line, in the state the server wrote
          // on it (`data-state`): failed, something for the reader to do
          // or see, or done. Copied, not composed.
          var first = outcome.querySelector("p");
          var state = (first && first.dataset.state) || "done";
          if (first) {
            setText(".job-step", first.textContent);
            announce(first.textContent, true);
          }
          panel.dataset.state = state;
          // What asks something of the reader is shown, not left behind a
          // click: the panel opens itself once.
          var popover = panel.querySelector("[popover]");
          if (popover && popover.showPopover && state !== "done" &&
              !popover.matches(":popover-open")) {
            popover.showPopover();
          }
          // The outcome is the record and the live lines were progress:
          // an outcome that lists its items replaces theirs, or a finished
          // sync lists every document twice. A warning stays: the
          // outcome does not repeat it.
          if (outcome.querySelector(".items, .group")) {
            lines.querySelectorAll("li[data-item]").forEach(function (line) {
              line.remove();
            });
          }
          if (window.htmx) { window.htmx.process(outcome); }
          // What else the outcome changed - the strip, the pane, a
          // backup's section - asked for again where this page has it.
          if (window.kennisRedraw) { window.kennisRedraw(outcome); }
          // Papers kennis could not fetch are asked for here, where the job
          // has just ended in front of the reader, and nowhere else: an
          // outcome drawn later by the server never reaches this, so the
          // question is not asked again on every page. A dialog the reader
          // already has open is left alone.
          var ask = outcome.querySelector("[data-ask-route]");
          var slot = document.getElementById("dialog");
          if (ask && slot && window.htmx && !slot.querySelector("dialog[open]")) {
            window.htmx.ajax("GET", ask.dataset.askRoute, {
              source: slot,
              target: slot,
              swap: "innerHTML",
            });
          }
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
      if (message.kind === "current") {
        setText(".job-step", message.text);
        announce(message.text, false);
        return;
      }
      if (message.kind === "elapsed") { setText(".job-clock", message.text); return; }
      if (message.kind === "began") {
        panel.dataset.state = "running";
        setText(".job-step", message.text);
        return;
      }
      if (message.kind === "progress") {
        Array.prototype.forEach.call(bars, function (bar) {
          bar.hidden = false;
          if (message.total) {
            bar.max = message.total;
            bar.value = message.completed;
          } else {
            bar.removeAttribute("value");
          }
        });
        setText(".job-count", message.text);
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
