// Tell the reader when something other than this window has written to
// the corpus while it sat open. Concern #311; a dialog since 2026-10-17.
//
// **On focus, not on a timer.** A timer spends a subprocess a minute,
// forever, answering a question nobody asked; returning to the window
// is the moment the answer starts mattering, and this costs nothing
// while the window is in the background.
//
// **The page's revision moves with this window's own writes.** It was
// read once at load, so an add, a note or a move made here - none of
// which reloads the page - was announced on the next focus as something
// else changing the corpus. The server answers each of this window's
// writes with the commit it left, in `X-Kennis-Revision`, and only those:
// a search answering it would hide a terminal's write behind a keystroke.
// A job's outcome carries it too, and arrives as `kennis:written`.
//
// **Not now is remembered for that change only.** Dismissing records
// the revision it was asked about, so the next focus does not ask again
// until something else is written. Every word is the server's: the
// dialog is drawn whole, and what changed arrives as `change`.
(function () {
  var dialog = document.getElementById("corpus-changed");
  if (!dialog) { return; }
  var dismissed = "";
  var said = dialog.querySelector("[data-change]");

  function check() {
    if (document.hidden || dialog.open) { return; }
    fetch("/revision", { credentials: "same-origin" })
      .then(function (answer) { return answer.ok ? answer.json() : null; })
      .then(function (body) {
        if (!body || body.revision === dialog.dataset.revision) { return; }
        if (body.revision === dismissed) { return; }
        dialog.dataset.asked = body.revision;
        said.textContent = body.change || "";
        dialog.showModal();
      })
      .catch(function () {
        // A failed check says nothing. Saying "the corpus changed"
        // because a request failed would be a false claim, and the
        // page is still perfectly readable.
      });
  }

  // Escape closes a modal dialog natively, so closing by any means is
  // Not now; Reload leaves the page before it matters.
  dialog.addEventListener("close", function () {
    dismissed = dialog.dataset.asked || "";
  });
  dialog.querySelector("[data-later]").addEventListener("click", function () {
    dialog.close();
  });
  dialog.querySelector("[data-reload]").addEventListener("click", function () {
    window.location.reload();
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    var request = event.detail && event.detail.xhr;
    var written = request && request.getResponseHeader("X-Kennis-Revision");
    if (written) { dialog.dataset.revision = written; }
  });

  // A job's outcome is fetched outside htmx, by `progress.js`, which
  // passes the header on.
  document.body.addEventListener("kennis:written", function (event) {
    var written = event.detail && event.detail.revision;
    if (written) { dialog.dataset.revision = written; }
  });

  window.addEventListener("focus", check);
  document.addEventListener("visibilitychange", check);
})();
