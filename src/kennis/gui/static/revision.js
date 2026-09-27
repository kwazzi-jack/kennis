// Tell the reader when a terminal has written to the corpus while this
// window sat open. Concern #311.
//
// **On focus, not on a timer.** A timer spends a subprocess a minute,
// forever, answering a question nobody asked; returning to the window
// is the moment the answer starts mattering, and this costs nothing
// while the window is in the background.
(function () {
  var banner = document.getElementById("corpus-changed");
  if (!banner) { return; }
  var drawnAt = banner.dataset.revision;

  function check() {
    if (document.hidden) { return; }
    fetch("/revision", { credentials: "same-origin" })
      .then(function (answer) { return answer.ok ? answer.json() : null; })
      .then(function (body) {
        if (!body || body.revision === drawnAt) { return; }
        banner.textContent = banner.dataset.message;
        banner.hidden = false;
      })
      .catch(function () {
        // A failed check says nothing. Showing "the corpus changed"
        // because a request failed would be a false claim, and the
        // page is still perfectly readable.
      });
  }

  window.addEventListener("focus", check);
  document.addEventListener("visibilitychange", check);
})();
