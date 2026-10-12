// Tell the reader when a terminal has written to the corpus while this
// window sat open. Concern #311.
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
(function () {
  var banner = document.getElementById("corpus-changed");
  if (!banner) { return; }

  function check() {
    if (document.hidden) { return; }
    fetch("/revision", { credentials: "same-origin" })
      .then(function (answer) { return answer.ok ? answer.json() : null; })
      .then(function (body) {
        if (!body || body.revision === banner.dataset.revision) { return; }
        banner.textContent = banner.dataset.message;
        banner.hidden = false;
      })
      .catch(function () {
        // A failed check says nothing. Showing "the corpus changed"
        // because a request failed would be a false claim, and the
        // page is still perfectly readable.
      });
  }

  document.body.addEventListener("htmx:afterRequest", function (event) {
    var request = event.detail && event.detail.xhr;
    var written = request && request.getResponseHeader("X-Kennis-Revision");
    if (written) { banner.dataset.revision = written; }
  });

  window.addEventListener("focus", check);
  document.addEventListener("visibilitychange", check);
})();
