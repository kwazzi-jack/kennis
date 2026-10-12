# The text fits the pane, and a passage says which section it is

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12: "Can we increase the view width or decrease the
margins? We can make the current mode an option in the settings, but
default should try fit the pane should it not? Also, could we somehow
improve the look of the heading? Or just do formatting or styling to
make it easier to work with and understand per chunk."

Measured first: at 1280px the results are 528px wide (33rem, the
reading measure) inside a 1024px pane, so nearly half the pane is
margin. Every hit's heading is the command line's headline less its
rank - "document title - section" - in the green serif, so two hits
from one paper repeat a two-line title and the part that differs, the
section, is at the end of it.

1. **A width preference**, "Text width": *Fit the pane* (the default,
   no cap), *Wide* (56rem) and *Reading measure* (the 33rem the window
   has had until now). A cookie drawn onto `<html>` like the others.
2. **Less padding** at the top of the centre pane.
3. **The heading is split.** The title above the card is the document's
   title alone, in the interface's sans, a step smaller. The section is
   the card's own header - a `#` icon and the section's words over a
   hairline - so the card reads as "this passage, from this section",
   and two hits from one paper differ where they actually differ. A
   leading heading in the passage that repeats the section is dropped
   from the passage's tokens, since the header already says it; the
   reader's words are marked in the header as in the text.

## How I expect it to work

- `render/hits.py::hit_title_parts(result)` returns `(title, section or
  None)` by the rule `hit_title` already uses (a section equal to the
  title in case-folded form carries nothing); `hit_title` joins them,
  so the headline is unchanged. `RenderedHit.title` becomes
  `document_title` and `section`.
- `render/html.py::passage_html(..., section=)` drops a first top-level
  heading whose text is the section, and returns `PassageHtml.heading`,
  the section escaped and marked, empty when there is none.
- `ShownHit` carries `title` and the passage; `hits.html` draws
  `<p class="passage-section">` first inside `.full` when `heading`.
- Width: `--text` and `--frame` on `:root`, `none` by default;
  `data-width="wide"` and `"reading"` set them. `.column` takes
  `--frame`, and every `max-width: var(--measure)` on results and
  `article` becomes `var(--text)`. The reading choice restores exactly
  the old values: `--frame` is `calc(margin + gap + measure)`.

## What I expect to be uncertain or difficult

- The test that the window's title is the headline less its rank must
  now compare the joined pair, or it stops saying anything.
- A section whose heading in the chunk is spelled differently from
  `Chunk.section` (markup inside the heading) will not be dropped and
  will show twice. Acceptable; measure how often on the corpus.
- An unlimited measure on a document page: a very long line on a wide
  screen. That is what "fit the pane" means; the preference is there.
- The passage colour test refuses muted colour in a passage rule; the
  header's icon may want muted.

## What actually happened that I did not expect

- **The walk found a 500 the suite could not.** The corpus holds chunks
  that are only their heading; with it moved to the header nothing was
  left, and the block pairing in `passage_html` raised on empty tokens
  (`zip(..., strict=True)` of zero starts and one end). Every search
  reaching one answered Internal Server Error with 3707 tests green.
  Fixed with `pairwise`, tested, and drawn as the header alone; #456.
- **The header's hairline stopped short of the card's edges.**
  `.passage .full p` sets `margin` and outranked `.passage-section`, so
  the negative margins never applied. The rule is `.passage .full
  .passage-section` and the test reads that selector.
- Measured at 1280px with the pane open: a hit is 976px when fitting
  the pane, 896px wide, and 528px at the reading measure - the old
  width exactly. A document page fitting the pane beside the inspector
  is 704px.
- On the real corpus, 6 of 9 hits for "selfcal" and 6 of 9 for
  "calibration gains" have a section header; no card repeated its
  header as a heading inside it, so the sketch's worry about a heading
  spelled differently from `Chunk.section` did not show here.
- The header's icon is dimmed by `opacity` rather than drawn in the
  muted colour, because everything in a passage is in ink and a test
  says so; the effect is the same.
- Injections: eleven, all caught.
