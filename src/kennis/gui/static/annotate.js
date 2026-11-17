// Annotate a selection of a document's text, and draw each annotation
// over the text (#50; sketch 2026-11-16-annotate-selection).
//
// **Nothing here finds a selection in the document.** The page gives each
// top-level block `data-source`, where its markdown is; this script sends
// the selected text, as the reader sees it, with the blocks it begins and
// ends in, and the server finds the words in the markdown. A maths element
// contributes its TeX, which is what the markdown holds.
//
// **A highlight moves nothing.** Each annotation is drawn by the CSS Custom
// Highlight API, which paints ranges and adds no element, so a line of the
// document never moves for one (#674). The server says which words each
// annotation's range draws and where in the body it is; this script finds
// those words among the text nodes of the blocks the range reaches, the
// occurrence nearest the same relative place.
//
// Clicking a highlight opens its annotation; the inspector lists every
// annotation with an Edit link, which is the way in for the keyboard and
// for a page with no script. Nothing here composes a sentence.
(function () {
  var MOST_BEFORE = 64;
  var button = document.querySelector(".annotate-selection");
  var saved = null;

  function article() {
    return document.querySelector("article[data-annotate-document]");
  }

  function blockOf(node) {
    var element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    var block = element && element.closest("[data-source]");
    var text = article();
    return block && text && text.contains(block) ? block : null;
  }

  function sourceOf(block) {
    var parts = block.dataset.source.split(" ");
    return { start: Number(parts[0]), end: Number(parts[1]) };
  }

  // Whether a text node is text of the document as the reader reads it:
  // not kennis's own (a run's chips, a figure's notice), and for typeset
  // maths only its TeX, never KaTeX's drawing of it.
  function isDocumentText(node) {
    var parent = node.parentElement;
    if (!parent) { return false; }
    if (parent.closest(".tag-run-head, .figure-placeholder, script")) { return false; }
    if (parent.closest(".katex")) { return Boolean(parent.closest("annotation")); }
    return true;
  }

  function textNodesOf(root) {
    var nodes = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (isDocumentText(walker.currentNode)) { nodes.push(walker.currentNode); }
    }
    return nodes;
  }

  // An endpoint inside typeset maths moves to the whole of it, so the
  // selection carries the expression's TeX rather than part of a glyph.
  function widenedOverMaths(range) {
    var widened = range.cloneRange();
    var startElement = widened.startContainer.nodeType === Node.ELEMENT_NODE
      ? widened.startContainer : widened.startContainer.parentElement;
    var endElement = widened.endContainer.nodeType === Node.ELEMENT_NODE
      ? widened.endContainer : widened.endContainer.parentElement;
    var startMaths = startElement && startElement.closest(".katex");
    var endMaths = endElement && endElement.closest(".katex");
    if (startMaths) { widened.setStartBefore(startMaths); }
    if (endMaths) { widened.setEndAfter(endMaths); }
    return widened;
  }

  // The document's text within `range`, block by block.
  function textOf(range) {
    var pieces = [];
    var lastBlock = null;
    textNodesOf(range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentElement
      : range.commonAncestorContainer).forEach(function (node) {
      if (!range.intersectsNode(node)) { return; }
      var from = node === range.startContainer ? range.startOffset : 0;
      var to = node === range.endContainer ? range.endOffset : node.data.length;
      var block = blockOf(node);
      if (lastBlock && block !== lastBlock) { pieces.push("\n"); }
      lastBlock = block;
      pieces.push(node.data.slice(from, to));
    });
    return pieces.join("");
  }

  function hide() {
    if (button) { button.hidden = true; }
    saved = null;
  }

  function offer() {
    var selection = window.getSelection();
    if (!button || !selection || selection.isCollapsed || !selection.rangeCount) {
      hide();
      return;
    }
    var range = selection.getRangeAt(0);
    var first = blockOf(range.startContainer);
    var last = blockOf(range.endContainer);
    if (!first || !last || !range.toString().trim()) { hide(); return; }
    var rectangles = range.getClientRects();
    var corner = rectangles[rectangles.length - 1];
    if (!corner) { hide(); return; }
    saved = range.cloneRange();
    button.hidden = false;
    var width = button.offsetWidth;
    button.style.left = Math.max(8, Math.min(corner.right - width, window.innerWidth - width - 8)) + "px";
    button.style.top = Math.min(corner.bottom + 6, window.innerHeight - button.offsetHeight - 8) + "px";
  }

  var pending = null;
  document.addEventListener("selectionchange", function () {
    clearTimeout(pending);
    pending = setTimeout(offer, 120);
  });
  var reading = document.querySelector(".reading");
  if (reading) { reading.addEventListener("scroll", function () { if (saved) { offer(); } }); }

  if (button) {
    // Pressing the button must not take the selection away first.
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () {
      var text = article();
      if (!saved || !text || !window.htmx) { return; }
      var range = widenedOverMaths(saved);
      var first = blockOf(range.startContainer);
      var last = blockOf(range.endContainer);
      if (!first || !last) { return; }
      var before = document.createRange();
      before.setStart(first, 0);
      before.setEnd(range.startContainer, range.startOffset);
      var values = {
        document: text.dataset.annotateDocument,
        first: first.dataset.source,
        last: last.dataset.source,
        text: textOf(range),
        before: textOf(before).slice(-MOST_BEFORE)
      };
      if (text.dataset.annotateCollection) { values.collection = text.dataset.annotateCollection; }
      if (text.dataset.annotateProject) { values.project = text.dataset.annotateProject; }
      hide();
      window.htmx.ajax("POST", "/annotate/located", {
        source: button, target: "#dialog", swap: "innerHTML", values: values
      });
    });
  }

  // ---------------------------------------------------------------------
  // Drawing each annotation over the text

  var drawn = [];

  // Each highlight is painted by the rule for its name, and a name is a
  // colour (`theme.highlight_name`), so the ranges are grouped by name.
  // `names` is what was set last time under each kind, which the next
  // draw clears; the two kinds are cleared apart, so a page drawing both
  // keeps both.
  var names = { annotation: [], "annotated-passage": [] };

  function paintAll(kind, ranges) {
    var supported = window.CSS && CSS.highlights && typeof Highlight === "function";
    if (!supported) { return; }
    names[kind].forEach(function (name) { CSS.highlights.delete(name); });
    var grouped = {};
    ranges.forEach(function (one) {
      var name = one.paint || kind;
      (grouped[name] = grouped[name] || []).push(one.range);
    });
    names[kind] = Object.keys(grouped);
    names[kind].forEach(function (name) {
      CSS.highlights.set(name, new Highlight(...grouped[name]));
    });
  }

  function wordsPattern(words) {
    var escaped = words.map(function (word) {
      return word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    });
    return new RegExp(escaped.join("[^\\p{L}\\p{N}\\p{M}_]+"), "gu");
  }

  // The range of the page drawing `found`'s words, or null.
  function rangeOf(found, blocks) {
    var reached = blocks.filter(function (block) {
      var source = sourceOf(block);
      return source.start < found.end && source.end > found.start;
    });
    if (!reached.length || !found.words.length) { return null; }
    var segments = [];
    var joined = "";
    reached.forEach(function (block, position) {
      if (position > 0) { joined += "\n"; }
      textNodesOf(block).forEach(function (node) {
        segments.push({ node: node, start: joined.length });
        joined += node.data;
      });
    });
    var first = sourceOf(reached[0]);
    var last = sourceOf(reached[reached.length - 1]);
    var expected = (found.start - first.start) / Math.max(1, last.end - first.start) * joined.length;
    var pattern = wordsPattern(found.words);
    var best = null;
    var match;
    while ((match = pattern.exec(joined)) !== null) {
      if (!best || Math.abs(match.index - expected) < Math.abs(best.index - expected)) {
        best = { index: match.index, end: match.index + match[0].length };
      }
      if (match[0].length === 0) { pattern.lastIndex += 1; }
    }
    if (!best) { return null; }
    var start = pointIn(segments, best.index, false);
    var end = pointIn(segments, best.end, true);
    if (!start || !end) { return null; }
    var range = document.createRange();
    range.setStart(start.node, start.offset);
    range.setEnd(end.node, end.offset);
    return range;
  }

  function draw() {
    drawn = [];
    var text = article();
    var data = text && text.querySelector("script[data-annotations]");
    if (!data) { paintAll("annotation", []); return; }
    var annotations = [];
    try { annotations = JSON.parse(data.textContent); } catch (error) { return; }
    var blocks = Array.prototype.slice.call(text.querySelectorAll("[data-source]"));
    annotations.forEach(function (found) {
      var range = rangeOf(found, blocks);
      if (range) { drawn.push({ range: range, href: found.href, id: found.id, paint: found.paint }); }
    });
    paintAll("annotation", drawn);
    text.dataset.highlighted = String(drawn.length);
  }

  // A search passage a tag admitted (#50, unit 3b): the words of each
  // annotation, found in the passage's text as the document page finds
  // them - the occurrence nearest where the annotation starts - drawn under
  // a name of their own so the page's own highlights are not replaced.
  function drawPassages() {
    var ranges = [];
    document.querySelectorAll("[data-annotated]").forEach(function (passage) {
      var lists = [];
      try { lists = JSON.parse(passage.dataset.annotated); } catch (error) { return; }
      var segments = [];
      var joined = "";
      textNodesOf(passage).forEach(function (node) {
        segments.push({ node: node, start: joined.length });
        joined += node.data;
      });
      var count = 0;
      lists.forEach(function (found) {
        if (!found.words || !found.words.length) { return; }
        var expected = found.at * joined.length;
        var pattern = wordsPattern(found.words);
        var best = null;
        var match;
        while ((match = pattern.exec(joined)) !== null) {
          if (!best || Math.abs(match.index - expected) < Math.abs(best.index - expected)) {
            best = { index: match.index, end: match.index + match[0].length };
          }
          if (match[0].length === 0) { pattern.lastIndex += 1; }
        }
        if (!best) { return; }
        var start = pointIn(segments, best.index, false);
        var end = pointIn(segments, best.end, true);
        if (!start || !end) { return; }
        var range = document.createRange();
        range.setStart(start.node, start.offset);
        range.setEnd(end.node, end.offset);
        ranges.push({ range: range, paint: found.paint });
        count += 1;
      });
      passage.dataset.highlighted = String(count);
    });
    paintAll("annotated-passage", ranges);
  }

  // The text node and offset at `offset` of the joined text of `segments`;
  // `closing` puts an offset on a boundary at the end of the node before.
  function pointIn(segments, offset, closing) {
    for (var index = segments.length - 1; index >= 0; index -= 1) {
      var segment = segments[index];
      var inside = closing ? segment.start < offset : segment.start <= offset;
      if (inside) { return { node: segment.node, offset: Math.min(offset - segment.start, segment.node.data.length) }; }
    }
    return null;
  }

  // What is drawn, for a test to read: each highlight's text and the text
  // of its block before it.
  window.kennisAnnotations = function () {
    return drawn.map(function (one) {
      var before = document.createRange();
      before.setStart(blockOf(one.range.startContainer), 0);
      before.setEnd(one.range.startContainer, one.range.startOffset);
      return { id: one.id, paint: one.paint, text: one.range.toString(), before: before.toString() };
    });
  };

  function pointAt(x, y) {
    if (document.caretPositionFromPoint) {
      var position = document.caretPositionFromPoint(x, y);
      return position && { node: position.offsetNode, offset: position.offset };
    }
    if (document.caretRangeFromPoint) {
      var range = document.caretRangeFromPoint(x, y);
      return range && { node: range.startContainer, offset: range.startOffset };
    }
    return null;
  }

  document.addEventListener("click", function (event) {
    var text = article();
    if (!text || !text.contains(event.target) || !window.htmx) { return; }
    if (event.target.closest("a, button, summary, input, textarea")) { return; }
    var selection = window.getSelection();
    if (selection && !selection.isCollapsed) { return; }
    var point = pointAt(event.clientX, event.clientY);
    if (!point) { return; }
    var under = drawn.filter(function (one) {
      try { return one.range.isPointInRange(point.node, point.offset); } catch (error) { return false; }
    });
    if (!under.length) { return; }
    under.sort(function (one, other) { return one.range.toString().length - other.range.toString().length; });
    window.htmx.ajax("GET", under[0].href, { source: text, target: "#dialog", swap: "innerHTML" });
  });

  document.addEventListener("DOMContentLoaded", draw);
  document.addEventListener("DOMContentLoaded", drawPassages);
  document.body.addEventListener("htmx:afterSwap", function () {
    var text = article();
    if (text && typeof typeset === "function") { typeset(text); }
    draw();
    drawPassages();
  });
})();
