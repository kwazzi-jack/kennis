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
// Every word is the server's: the dialog is drawn whole, and only opened.
(function () {
  var ADDRESS = "/presence";

  function watch(report) {
    var opened = false;
    function connect() {
      opened = false;
      var source = new EventSource(ADDRESS);
      source.onopen = function () { opened = true; };
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
    var gone = false;
    self.onconnect = function (event) {
      var port = event.ports[0];
      ports.push(port);
      if (gone) { port.postMessage("gone"); }
    };
    watch(function () {
      gone = true;
      ports.forEach(function (port) { port.postMessage("gone"); });
    });
    return;
  }

  var dialog = document.getElementById("service-gone");
  if (!dialog) { return; }

  function show() {
    if (!dialog.open) { dialog.showModal(); }
  }

  // Nothing closes it: what is behind it can no longer answer.
  dialog.addEventListener("cancel", function (event) { event.preventDefault(); });

  if (typeof SharedWorker === "function") {
    var worker = new SharedWorker("/static/presence.js");
    worker.port.onmessage = function (event) {
      if (event.data === "gone") { show(); }
    };
    worker.port.start();
  } else {
    watch(show);
  }
})();
