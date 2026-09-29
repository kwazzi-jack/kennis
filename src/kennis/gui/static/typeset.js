// Typeset the elements `render/html.py` marked, once the page has
// loaded and again after htmx swaps content in. KaTeX's auto-render
// walks text looking for delimiters; here the delimiters are already
// gone and the maths is in elements, so each is rendered directly -
// which also means a document cannot inject a delimiter and have it
// typeset.
//
// **The selector is `.math`, not `span.math`.** A displayed equation
// is a `<div>`, so the narrower selector matched no display maths at
// all and the reader saw raw TeX on every equation a paper set on its
// own line.
//
// **`displayMode` is read from the class, not from the tag name.**
// `render/html.py` decides which forms are displayed and writes
// `display` on each; three of the four maths tokens carry it, and one
// of those three is a span. Asking the class list keeps that rule in
// one file.
function typeset(root) {
  if (typeof katex === "undefined") { return; }
  root.querySelectorAll(".math").forEach(function (node) {
    if (node.dataset.typeset === "yes") { return; }
    try {
      katex.render(node.textContent, node, {
        displayMode: node.classList.contains("display"),
        throwOnError: false
      });
      node.dataset.typeset = "yes";
    } catch (error) {
      // `throwOnError: false` already handles the ordinary failure:
      // KaTeX draws the expression it could not parse in its error
      // style, with the source text still legible, which is what a
      // reader needs to see. This catch is for the rest - a failure
      // that is not a parse error - and leaves the element as the
      // renderer wrote it rather than replacing it with a blank.
      node.dataset.typeset = "failed";
    }
  });
}

document.addEventListener("DOMContentLoaded", function () { typeset(document); });
document.body && document.body.addEventListener("htmx:afterSwap", function (event) {
  typeset(event.target);
});
