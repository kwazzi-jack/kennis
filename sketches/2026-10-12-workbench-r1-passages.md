# Realigning the workbench, 1: a passage as the mockup drew it

Milestone / step: milestone 11 realigned with the approved mockup
(Brian, 2026-10-12: "it does not really match the artefact")
Date: 2026-10-12

## What I am about to do

Fix the two passage defects Brian found, by building the passage the
mockup drew instead of the one 11c built.

1. An opened passage drew the window in ink and the text around it in
   the muted grey, so it read as two kinds of text. Neither the plan nor
   the mockup asked for that.
2. A table in a chunk arrived as a row of pipes, because the whole chunk
   was flattened into one inline paragraph.

## How I expect it to work

**The mockup's structure.** A hit's passage is
`<details class="passage" name="passages">`:
- the `<summary>` holds the snippet, an ellipsis at each side where
  text was left out, and "Show the whole passage" with a chevron;
- the body holds the whole chunk rendered as blocks, in ink, with the
  highlighter rule on its left, and "Open it in the document" under it.

`.passage[open] .snippet { display: none }`, so no text is on the page
twice: the closed snippet is replaced by the whole chunk, in the same
place. `name` closes the others when one opens. `<details>` opens with
no script, so `passage.js` and the `closed` class are removed. A reader
without a script now gets the same closed-and-openable passage instead
of every passage open. That is a change to #415's reasoning, which
chose "drawn whole" only because a script did the closing.

**The whole chunk** is `render/html.py::to_html(chunk, terms=...)`, the
document renderer, which already enables tables, renders maths with the
shared rule, and blocks remote images. `terms` is new: the reader's
words are marked on `text` tokens only, never inside code or maths. It
uses one pattern and one marker, which move from `gui/snippet.py` to
`render/html.py`, so the snippet and the passage cannot mark
differently (#376's lesson, about the two renderers).

**The snippet** stays `gui/snippet.py`'s inline runs, with the window
placed so the first match shows. `Passage` keeps `window`, gains
`whole`, and keeps `before` and `after` only as whether text was left
out on each side (`cut_before`, `cut_after`), since nothing draws them
now. A table inside a snippet is read with tables enabled: its cells
are separated by a middle dot the stylesheet draws, and the delimiter row disappears, instead of
`| --- |`.

## What I expect to be uncertain or difficult

- Whether `html_inline` tokens render their content when the parser
  was built with `html: False`. The option governs parsing, so I expect
  yes. Measure it.
- A chunk often starts mid-word ("vity, but also..."), because the
  packer cuts by size. The mockup's passage starts at a paragraph. Not
  fixed here; the opened passage starts with an ellipsis when the chunk
  starts mid-block, if that is cheap to know.
- Tables in the column: a wide table must scroll inside the passage,
  not widen the column.
- `test_gui_results.py` asserts the three-part seam property and
  `passage.js`. Those assertions describe the design being replaced, so
  they are rewritten, not worked around.

## What actually happened that I did not expect

- **`html_inline` does render under `html: False`**, as expected: the
  option governs the parser, not the renderer.
- **The first draft marked nothing in code, and an existing test said
  it should.** `test_a_term_inside_a_code_span_is_still_marked` records
  a decision made for the snippet: a search for `solve_gains` names the
  code. My new test asserted the opposite and passed only because its
  fixture, `antenna_gain`, cannot match "antenna" whole. That is #352's
  shape, and the injection exposed it. Both renderers now mark inline
  code.
- **The middle dot was a NUL.** The layout CSS is a Python string, so
  `"\00b7"` was read by Python as octal. The served stylesheet carried
  `\x00b7`, and the ASCII check passed, because NUL is ASCII. A test now
  refuses control characters in the stylesheet.
- **A link in the corpus's text had no colour.** In dark mode the
  references in an opened table were the browser's dark blue. Documents
  had the same defect. Both now use the command colour.
- **The colour test watched the wrong selectors.** It read only rules
  naming `.passage`, so muting `.full p` passed. It now reads every rule
  naming `.full`.
- Walked on Brian's corpus. The AstroLLaMA table opens as a table, in
  light and dark, and every cell and paragraph computes to ink. With
  scripts and without, opening a second passage closes the first.
- Injections: thirteen, all caught once the two tests above were fixed.
- Not done: a chunk that begins mid-word ("vity, but also") still does,
  because the packer cuts by size.
