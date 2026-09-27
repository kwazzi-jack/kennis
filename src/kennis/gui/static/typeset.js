// Typeset the spans `render/html.py` marked, once the page has loaded
// and again after htmx swaps content in. KaTeX's auto-render walks
// text looking for delimiters; here the delimiters are already gone
// and the maths is in elements, so each is rendered directly - which
// also means a document cannot inject a delimiter and have it typeset.
function typeset(root) {
  if (typeof katex === "undefined") { return; }
  root.querySelectorAll("span.math").forEach(function (node) {
    if (node.dataset.typeset === "yes") { return; }
    try {
      katex.render(node.textContent, node, {
        displayMode: node.classList.contains("block"),
        throwOnError: false
      });
      node.dataset.typeset = "yes";
    } catch (error) {
      // Leave the source visible. A paper with one malformed
      // expression is still worth reading, and a blank is worse
      // than the TeX it came from.
      node.dataset.typeset = "failed";
    }
  });
}

document.addEventListener("DOMContentLoaded", function () { typeset(document); });
document.body && document.body.addEventListener("htmx:afterSwap", function (event) {
  typeset(event.target);
});
