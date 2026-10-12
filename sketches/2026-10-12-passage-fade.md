# A passage drawn once, faded where it is cut, and grown in place

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12, on tables in a closed passage: a placeholder ("table,
expand to see"), or "switch the passage display to a fade animation ...
render the full thing, hide the excess with a fade, then if they open
the passage, the fade moves down and the whole thing simply opens."

**The fade**, because a placeholder answers tables and nothing else: a
code block, a list, display maths and a heading each need their own
rule in a closed passage, and each rule is a way for the two views to
disagree. With the fade there is one rendering, the document
renderer's, and the closed view is a window onto it. It is also what
plan 11c asked for before R1: "the text before and after the window
appearing in place around it ... the height slides".

## How I expect it to work

**One rendering, in two parts.** `render/html.py` gains
`passage_html(markdown, terms, fits)`: parse, mark the terms, find the
first top-level block whose text holds a match, and render the blocks
before it and the blocks from it separately, with whether the second
part fits within `fits` characters and holds no table, code block or
display equation. No match (a meaning-only hit) puts everything in the
second part. Top-level blocks are whole subtrees, so each part renders
on its own.

**The page.**

    <div class="passage clamped">
      <div class="lead">blocks before the first match</div>
      <div class="body">the rest, from the match</div>
      <details name="passages"><summary>Show the whole passage</summary></details>
      <p class="go">Open it in the document</p>
    </div>

Closed: `.lead` has height 0 and `.body` a fixed height, faded at the
bottom (and at the top when a lead exists) with `mask-image`. Opened -
`.passage:has(> details[open])` - both become `height: auto`, the masks
go, and `interpolate-size: allow-keywords` lets the heights transition
where the browser supports it (Chromium); elsewhere the change is
immediate. `<details name>` still closes the others with no script, and
a reader without a script gets the same thing.

`clamped` only when there is something to open: a lead, or a body that
does not fit. A short passage is drawn whole with no toggle.

**What goes.** `gui/snippet.py`'s inline window - runs, cuts, TeX as a
third kind of run - has no caller once the window is not drawn. It is
removed with its tests, and `terms_of` moves beside `query_pattern`.
The marking rules its tests stated (whole word, case, escaping, never in
maths) are kept by rewriting those tests against `to_html`, which is
what draws the passage now. CLAUDE.md's invariants about the snippet
window are rewritten.

## What I expect to be uncertain or difficult

- Whether a mask on a block containing KaTeX output or a scrolling table
  behaves.
- The fixed height in `em` against the reading face and size
  preferences, which change the line height.
- `fits` is counted in source characters; the page measures in lines. A
  passage just over the count may fit and still be faded. Measure.
- The jump: opening adds text above the matched paragraph, so it moves
  down. The height transition should make that read as growing.

## What actually happened that I did not expect

- **A note's title heading made every short note open.** The chunk
  carries `# calibration`, so the match was in the second block and the
  lead held one line; offering "Show the whole passage" to reveal a
  heading is noise. `fits` counts the lead as well as the body, and a
  passage that fits is drawn whole with no control. `opens` is just
  `not fits` now.
- **A table hid the match.** The sketch's parting is at top-level
  blocks and a table is one, so on `uTBD` the closed view showed the
  head of a 25-row table and no `uTBD`. Fixed by `passage.js`, which
  scrolls the clipped body (`overflow: hidden` still scrolls by
  assignment) so the first mark sits a third of the way down, and sets
  `data-shifted` for a fade at the top. So "no script is involved" is
  no longer true; without one the passage shows its first lines.
- **`toggle` fires while a closing body is still tall**, so the shift
  measured then was 0 and a passage closed again showed the table head.
  It measures again on `transitionend`; `toggle` stays for reduced
  motion, where nothing transitions.
- **A heading-only chunk** ("2 Data") drew at a document's `h2` size in
  the results. Headings in a passage are the text's size, in weight.
- The fade on a scrolling table and on KaTeX output behaved: the mask
  is on `.body`, which clips, so nothing inside it needed to know.
- `fits` in characters against six lines: measured 163px closed for a
  360-character limit; the selfcal passage (272px whole) clamps and
  grows, the blockquote of 196 characters fits whole. Not tuned further.
- The jump I expected on opening is real when there is a lead, and
  softened by the height transition: 163px -> 477px at 120ms -> 812px.
- `without_empty_options` was public only for `gui/snippet.py`; private.
- Injections: twenty, all caught.
