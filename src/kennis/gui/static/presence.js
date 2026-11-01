// An open window keeps the service, and says when it has gone (Brian,
// 2026-10-30; `gui/presence.py` is the server's half).
//
// **One connection for every kennis tab.** A browser allows six HTTP/1.1
// connections to one host across all its tabs, and a running job's
// progress takes one more; a stream held by each tab would leave a later
// request waiting with nothing to say why. So this file is also the shared
// worker that holds the one stream, and each page only listens to it. A
// browser without `SharedWorker` watches from the page.
//
// **No timer.** The server ends the stream when it stops. A stream that
// had opened and then ended is asked for once more, which also covers a tab
// the browser froze and woke; a stream that ends before it opens is the
// service gone - a 204, which the server answers once it is stopping, or a
// refused connection once it has stopped.
//
// **A passage shown here rather than in a new tab** (Brian, 2026-11-01).
// `kennis open` makes the service send a `show` event down the stream. The
// worker passes it to the page that last had focus, else the last to
// connect; that page asks `POST /shown/<nonce>` and moves only on 204,
// because a 410 means the service stopped waiting and a new tab was opened.
//
// Every word is the server's: the dialog is drawn whole, and only opened.
(function () {
  var ADDRESS = "/presence";

  function watch(report, told) {
    var opened = false;
    function connect() {
      opened = false;
      var source = new EventSource(ADDRESS);
      source.onopen = function () { opened = true; };
      source.addEventListener("show", function (event) { told(event.data); });
      source.onerror = function () {
        source.close();
        if (opened) { connect(); } else { report(); }
      };
    }
    connect();
  }

  if (typeof document === "undefined") {
    // The shared worker: one watch, told to every page that connects,
    // including one that connects after the service has gone.
    var ports = [];
    var focused = null;
    var gone = false;
    self.onconnect = function (event) {
      var port = event.ports[0];
      ports.push(port);
      port.onmessage = function (message) {
        if (message.data === "focused") {
          // Also a page the browser kept and brought back after `closing`.
          if (ports.indexOf(port) < 0) { ports.push(port); }
          focused = port;
        } else if (message.data === "closing") {
          ports = ports.filter(function (each) { return each !== port; });
          if (focused === port) { focused = null; }
        }
      };
      port.start();
      if (gone) { port.postMessage("gone"); }
    };
    watch(function () {
      gone = true;
      ports.forEach(function (port) { port.postMessage("gone"); });
    }, function (data) {
      var target = focused !== null ? focused : ports[ports.length - 1];
      if (target) { target.postMessage({ show: data }); }
    });
    return;
  }

  var dialog = document.getElementById("service-gone");
  if (!dialog) { return; }

  function show() {
    if (!dialog.open) { dialog.showModal(); }
  }

  function showHere(data) {
    var asked;
    try { asked = JSON.parse(data); } catch (error) { return; }
    // Only a path of this window: never another origin.
    if (typeof asked.path !== "string" || asked.path.charAt(0) !== "/" ||
        asked.path.charAt(1) === "/" || typeof asked.nonce !== "string") {
      return;
    }
    fetch("/shown/" + encodeURIComponent(asked.nonce), {
      method: "POST",
      credentials: "same-origin"
    }).then(function (answer) {
      if (answer.status === 204) {
        window.focus();
        location.assign(asked.path);
      }
    });
  }

  // Nothing closes it: what is behind it can no longer answer.
  dialog.addEventListener("cancel", function (event) { event.preventDefault(); });

  if (typeof SharedWorker === "function") {
    var worker = new SharedWorker("/static/presence.js");
    worker.port.onmessage = function (event) {
      if (event.data === "gone") {
        show();
      } else if (event.data && typeof event.data.show === "string") {
        showHere(event.data.show);
      }
    };
    worker.port.start();
    if (document.hasFocus()) { worker.port.postMessage("focused"); }
    window.addEventListener("focus", function () {
      worker.port.postMessage("focused");
    });
    window.addEventListener("pagehide", function () {
      worker.port.postMessage("closing");
    });
  } else {
    watch(show, showHere);
  }
})();
