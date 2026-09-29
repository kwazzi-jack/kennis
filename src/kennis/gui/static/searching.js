// Say so while the hits on the page are not the hits for what is in
// the box.
//
// **It covers the wait, not the request.** `hx-trigger` debounces
// typing by 400ms and the request itself is about 12ms, so an
// indicator tied to the request would flash or be missed entirely.
// The reader's wait starts at the keystroke, so this does too.
//
// **Derived, not latched.** The obvious version shows on `input` and
// hides on `htmx:afterSwap`, and gets stuck: htmx's trigger is
// `input changed`, so typing a character and deleting it fires no
// request at all and the indicator never comes down. This instead
// recomputes one question - do the visible hits belong to what is in
// the form? - every time anything could change the answer. Nothing
// is remembered, so there is nothing to get stuck and no timer to
// paper over it.
//
// The comparison is exact and untrimmed on purpose: htmx sends the
// input's value verbatim and the server echoes it into the marker,
// so they are equal precisely when the results match the box.
(function () {
  var box = document.querySelector("input[name=q]");
  var where = document.querySelector("select[name=scope]");
  var how = document.querySelector("select[name=mode]");
  var indicator = document.getElementById("searching");
  if (!box || !where || !how || !indicator) { return; }

  function answered() {
    // Looked up each time, not held: the swap replaces it.
    return document.getElementById("answered");
  }

  function stale() {
    var shown = answered();
    if (!shown) { return false; }
    return box.value !== shown.dataset.query ||
      where.value !== shown.dataset.scope ||
      how.value !== shown.dataset.mode;
  }

  function reconsider() {
    indicator.hidden = !stale();
  }

  box.addEventListener("input", reconsider);
  where.addEventListener("change", reconsider);
  how.addEventListener("change", reconsider);
  document.body.addEventListener("htmx:afterSwap", reconsider);

  document.body.addEventListener("htmx:afterRequest", function (event) {
    // The one thing that is not derived. htmx does not swap on a
    // failed request, so the marker still names the old query and
    // "Searching" would be true of nothing. The next keystroke shows
    // it again, which is true again.
    if (event.detail && event.detail.successful === false) {
      indicator.hidden = true;
    }
  });
})();
