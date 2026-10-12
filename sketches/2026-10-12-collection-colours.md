# Each collection wears its own colour, everywhere it appears

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12: "to distinguish the collections, we should make each
a colour theme in terms of background, style and card ... because it is
hard to decipher which is part of which collection right now. We can
use that theme throughout including the file explorer right?"

Four collections - literature, docs, notes, and the project's context
bundle - each get one accent colour per theme. It is used for:

- **a hit's card**: the rule down the left, a tint in the head's band,
  a tint in the hairline border;
- **a group's heading**: its icon and the rule under it;
- **the pane**: a collection's icon in its row, and every document icon
  in its opened branch;
- **a document page**: the rule under the bar and the collection's
  crumb.

The open passage used to turn the card's left rule to the brand amber.
The rule now says which collection; an open card says it is open by a
wider rule instead (3px to 6px) - still a change of the same edge, and
not by colour alone.

**The colours were measured before they were chosen**
(`scratchpad/hues`), from the Okabe-Ito set, which was designed for
colour-vision deficiency, then moved in lightness until every pair
separated:

| | light | dark |
|---|---|---|
| literature | #0B6BA8 | #5BB2E6 |
| docs | #0A7B4C | #7FE0A8 |
| notes | #8A2F6B | #DA6A9A |
| context | #B14A12 | #EE8A57 |

Every one >= 4.5:1 against the ground and the raised surface; every
pair dE >= 50 and >= 20 under simulated deuteranopia (the worst,
docs-notes, 24.2); every one dE >= 20 from the brand. Each collection
also keeps its own icon, so the colour is never the only cue.

## How I expect it to work

- `gui/theme.py::COLLECTION_COLOURS`, beside `STRENGTH_SCALES`: chosen
  by meaning, so not the terminal palette. `css_variables` writes
  `--collection-<name>` in each theme block.
- The layout: `[data-collection="<name>"] { --collection:
  var(--collection-<name>); }`, so one attribute on an ancestor colours
  everything inside it; `--collection` defaults to the muted grey. The
  tints are `color-mix()` of `--collection` with the ground, so the
  layout still names no colour.
- `data-collection` on each `li.hit`, each `h2.group-head`, the pane's
  rows (already there) and the document page's `<main>`.
- Tests take the measurement helpers `test_gui_results.py` already has
  for the strength scales.

## What I expect to be uncertain or difficult

- `color-mix()` needs Chromium 111 / Firefox 113; older browsers drop
  the declaration and fall back to the plain border and ground.
- Whether a tinted head band in dark mode reads as a tint or as mud;
  look in both themes.
- The bundle's hits are grouped under `context`; the document page for
  a bundle file must carry `context` too.

## What actually happened that I did not expect
- **The first candidates failed the measurement, which is why it came
  first.** Okabe-Ito's bluish green and reddish purple, for docs and
  notes, were dE 11.7 apart as a deuteranope sees them in the light
  theme and 14.2 in the dark. A search over hue and lightness kept the
  hues and split the lightness: docs-notes is now 26.2 and 24.2.
- **The titles were a false signal once collections had colours.**
  Every title was the operation green, which on a literature or a
  notes card read as "docs". A title now wears its collection's colour,
  measured on its own band (9% of the colour over the ground): the
  closest is docs in the light theme at 4.52:1.
- The open card's rule had turned the brand; it now widens from 3px to
  6px, so the colour keeps saying which collection.
- Measured in the browser on the real corpus, both themes: each group's
  rule, each card's rule and head band resolve to the collection's
  colour; the pane's collection and document icons wear it while the
  chevrons stay grey; a document page's bar rule is its collection's.
- **Two injections missed, both the harness's fault, and found before
  touching a test.** Restoring only notes' old colour left a pair that
  still separated (dE 23.1) - inert; restoring both is caught. Deleting
  a loop's only line was a syntax error; replacing it is caught.
- Not coloured: the pane's state dots keep their own green and amber,
  which mean searchable and needs indexing, not a collection; the
  legend says so.
- Injections: nine, all caught after the two corrections.
