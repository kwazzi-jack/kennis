# 11c. Results, passages and the strength scale

Milestone / step: milestone 11, unit 11c (`design/plan.md`), concerns #406, #408, #415, #416, #417, #421
Date: 2026-10-10

## What I am about to do

Rebuild a search hit in the window: the measures above the title as a
coloured five-cell bar and a word, each measure named by an icon; one
passage element that shows its opening lines and opens in place to the
whole chunk; no rank number; one key at the head of the results instead
of a basis line per group. And rename the lexical measure "keywords" in
both front ends.

## How I expect it to work

**`render/hits.py` keeps owning the words.** `Leg` stays `"lexical" |
"meaning"` - the engine's names - and a new `LEG_LABELS` maps them to
what a person reads, `keywords` and `meaning`. `hit_detail_parts` prints
`keywords: high`, and `_LEG_SCALES` says "keywords as a fraction of the
best match here". The command line, the MCP tools and the window all
change together, because `rendered_hit` is the one renderer (#297).
`RenderedHit` gains `title` (the headline without its `[n] `) and
`measures` (the `(leg, level)` pairs), so the window can lay them out
without parsing a string. `headline` and `detail` stay byte-identical
across front ends; the window simply shows `title`, not `headline`.

**`gui/pages.py::ShownHit`** becomes: `title`, `measures` as
`ShownMeasure(leg, label, level, step)` with `step` 1..5 from the level,
`handle` (`id=... chunk=...`), `passage` (the whole chunk as marked
HTML), `href`. `detail_parts` goes from the window - it was the margin's.

**The passage** is `marked_snippet` with no limit - the same parser,
the same maths and marking rules - so the whole chunk is one HTML
fragment. It is drawn whole. `static/passage.js` then *clamps* each one
that is taller than four lines, scrolls the clamped box so the first
`<mark>` is in view (a match late in a chunk still shows closed - what
the mockup promised), and reveals a toggle whose two labels come from
the server in `data-` attributes. Opening animates the height, turns
the chevron and closes any other open passage. Without a script nothing
is clamped and the whole passage shows - degraded, not broken.

**The key** is a `<details>` at the head of `#hits`: its summary is an
info icon, "What the measures mean" and the five-step ramp between
"low" and "very high"; opened, one line per measure present (its icon,
its label, its scale phrase) and a line on ordering. No script, so it
works without one. Each group keeps its collection heading and loses its
basis line (#408 relaxed to "the scale is on the page").

**The scale** is data in `gui/theme.py`: five named scales, five steps
each, per theme, emitted as `--strength-1..5` in the same three theme
blocks as every other colour. Viridis is the default; choosing is
milestone 12. Only the bar is coloured (#421). A filled cell is
`--strength-N` for the hit's own level N, so the whole bar is the colour
of its level, and empty cells are the rule colour.

**The mode control** reads "Keywords only", "Meaning only", "Keywords
and meaning" (#417).

## What I expect to be uncertain or difficult

- Tests that pin `lexical:` in output (`test_hits.py`, `test_cli_search.py`)
  and the window tests that compare whole headlines with the command
  line; they must be rewritten to state the new shape, not loosened.
- Scrolling a clamped box to its first mark: `overflow: hidden` still
  allows `scrollTop` to be set from script, I believe, but have not
  measured it.
- Animating to an unknown height needs the measured `scrollHeight`;
  KaTeX typesets after load and changes heights, so the clamp has to be
  decided after typesetting or re-decided on open.
- The dark grey scale: matplotlib's Greys flattens near white, so its
  steps are written by hand and the deuteranopia test decides.

## What actually happened that I did not expect

- **The sketch's passage was not the plan's.** I sketched one chunk drawn
  whole and clamped to four lines by the script, scrolled to its first
  mark. The plan, which is what Brian agreed on 2026-10-09, says three
  runs - before, window, after - with an ellipsis where text was left
  out, so the closed passage is the snippet window placed around the
  first match. Built the plan's: `snippet.py::passage_of` splits the same
  runs `marked_snippet` reads, at word boundaries, with TeX never cut and
  a tag open at a seam closed on one side and reopened on the other. No
  scrolling and no measuring of heights after KaTeX, so two of the
  sketch's uncertainties never arose. The test the plan named - before +
  window + after is the chunk, nothing lost or repeated - is the one
  written.
- **The plan's reorder control belonged here and the sketch missed it.**
  Milestone 11's principles say the reader may reorder within a
  collection by one leg's own rank with the limit stated (#406). Built as
  links, offered only when both measures scored, because with one the
  list is already in that leg's order.
- **A cut at offset 0 left `<strong></strong>` before the window.** A
  one-line note under a heading got a toggle and a leading ellipsis: the
  part was a non-empty string with no text in it. Found walking the
  window, not by a test; the test came after.
- **`.bar` was already the header.** My cell group took the name and its
  `display: inline-flex` reached the top bar, and the progress-bar look
  drew a line under every measure. Obvious in a screenshot, invisible to
  the suite. A test now fails if the layout declares a bare class twice
  (#425).
- **"lexical" was in more places than the hit line.** The fallback
  warning said "ran as a lexical search", which beside a control reading
  "Keywords only" is the two-vocabularies problem #382 was about. Now
  "has no meaning leg, so this matched keywords only". Six tests asserted
  "no dense leg" *absent*; renaming the sentence would have made every one
  of them pass for nothing, so they were rewritten with it.
- **A textual negative failed on the fixture's prose again.** "no element
  is `closed`" was first written as `"closed" not in page`, and the
  fixture's own sentence says "a closed snippet". Now asserted on class
  attributes. The same lesson as #337, written in the same hour as the
  code, again.
- **Two injections were not caught and neither test was hollow.** The
  key-per-group injection was a template syntax error (the harness
  reported errors, not a failure); and with one collection, a key drawn
  per group is also drawn once - so the test now searches two. The
  unbalanced-tags fixture never produced emphasis, because a closing `*`
  after a space is not a delimiter - the property held for want of a
  tag (#352's shape). Both corrected; 29 injections, all caught.
- **The docs were stale before this unit.** The tutorial and the
  retrieval explanation still showed v0.7a's single `relevance:` band.
  Rewritten from a real run.
- **The passage repeats the title.** A chunk that starts with the
  document's heading shows it in bold before the text, so "Short" reads
  "Short Short An antenna note". The same thing #353 fixed for documents;
  not fixed here (#426).
