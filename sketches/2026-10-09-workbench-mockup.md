# The workbench, drawn before it is built

Milestone / step: off-plan, branch `gui-workbench` (Brian, 2026-10-09)
Date: 2026-10-09

## What I am about to do

Draw the three-pane workbench as a static page in kennis's own palette and
publish it for Brian to approve, before any template changes. No product
code in this unit.

## How I expect it to work

One HTML file, outside the repository, with the palette copied from
`gui/theme.py` (`LIGHT_GROUND`, `DARK_GROUND` and the nine ANSI names, both
themes) and the three faces (`--column`, `--gutter`, `--mono`). It shows:

- a top bar: wordmark, the search box with scope and mode, and the actions
  as icon buttons - Add, Note, Index, Sync, Install pack;
- a left pane, Library: each collection with its count and index freshness,
  a stale one carrying a Rebuild button; then the Project bundle; then
  Activity;
- the centre: search hits in the existing margin-and-column layout, with a
  switch to a document open with its chunk marked, and to the Add dialog;
- a bottom strip: the job, in three states - idle, running (current item
  named, count, elapsed), finished (headline and a link to the outcome).

The states are switchable in the mockup only, so one page shows all of them.

## What I expect to be uncertain or difficult

- Whether the margin-and-column hit layout still reads in a centre pane that
  is narrower than the full window was.
- Where the theme control goes once the sidebar is a library tree.
- Whether the bottom strip competes with the reading column on a short
  window; it may need to collapse to one line.

## What actually happened that I did not expect

Published as https://claude.ai/artifact/5R5p4wvprfhTB6rANr5boG (private).

- The margin-and-column hit layout survives the narrower centre: at 1280px
  wide with a 15rem library pane the column keeps its full 33rem measure, so
  the first uncertainty did not materialise at that width. Below 760px the
  margin folds onto one line above the hit.
- The theme control fitted at the end of the toolbar, not in the library
  pane, which settles the second uncertainty; a preference sits with the
  actions, not with the places.
- The strip is one line while running and grows only when "Details" is
  opened, so it did not compete with the column.
- `.scrim { display: grid }` beat the `hidden` attribute, so the dialog
  showed on load. The real templates will need `[hidden] { display: none
  !important; }` in the stylesheet once dialogs exist there.
- The first draft named "Packs" both a toolbar action and a place in the
  pane. Whether installing a pack is an action or a page is open for Brian.

### Second round (Brian's review, same day)

Version 3 of the same artifact. What changed and what it rests on:

- **Library -> Corpus**, drawn as a file tree: collection -> group ->
  document, with `<details>` so it opens without a script. The collections
  are a fixed set (`schema.py::COLLECTION_NAMES` = literature, docs, notes),
  which is what makes one icon per collection sound: an icon names a kind,
  and there are exactly three kinds. The mockup's "papers" was wrong.
- **Context is headed by the project's name**, taken from the bundle's
  parent directory - the manifest carries no name. Only the one bundle
  `find_bundle` finds; other projects' bundles would be a backend change.
- **Each result shows its combined place and each leg's own rank.**
  `SearchResult` already carries `bm25_rank` and `dense_rank` beside the
  fused `score`, so "lexical #3, meaning #1, combined 1" is data the engine
  has, not a new computation.
- **Ordering by a leg reorders what was found; it does not search again.**
  With `default_top_k` = 3 per scope that is a reordering of three hits.
  The mockup says so under the results and points at the mode control,
  which is the real way to search by one leg.
- **Document metadata moved to an inspector** that slides over the right
  margin, so the column keeps its measure whether it is open or not.
- **Add is per kind**: Paper (identifier or a PDF, with live recognition
  of what was typed), Documentation site (address, project, page limits),
  Note file. The paste-many box is a disclosure under Paper.
- **The wordmark is the vendored Source Serif 4's own outlines** with the
  i's dot replaced by the highlighter swatch; a `k` monogram for narrow
  windows. No new font is vendored.
- A command palette (Ctrl K) over the same actions and places, and an idle
  status strip that says what is held and what needs attention.

What I did not expect: the rank caption under each numeral collided with
the leg column at a 9.5rem margin; it says the same thing for every hit in
a collection, so it moved to the collection's header once. And a sed-style
string edit with no check of its own applied nothing and was published -
the third time #66's lesson has applied to something that is not a test.

### Third round (Brian's review, same day)

Version 4 of the artifact.

- **No numbered ranks.** A place number reads as a measurement it is not.
  The hit keeps the stacked layout, its measures move *above* the title,
  and the measure that placed it is outlined: the leg whose own rank of
  the hit is better, which is the leg that contributed more to the
  reciprocal-rank sum. Neither outlined when they tie or only one leg ran.
- **Bars are coloured by level**, one hue rising in weight, never red to
  green: a weak match is not an error. Whether bars, words or both show is
  a setting of the window.
- **The whole passage is in the hit, closed.** `<details name="passages">`
  makes opening one close the others with no script - verified in the
  headless shell (two clicks leave only the second open). Whether
  pywebview's WebKitGTK honours `name` is unverified; without it several
  stay open, which is a tolerable failure.
- **The scale sentences and the model name moved behind an info button**
  on each collection's heading. This relaxes the invariant "relevance is
  never shown without its scale" - see #408.
- **The palette is one list**, kind on the right, Up and Down wrap -
  verified by walking all 15 entries. The categorised version did move
  across sections in the headless shell; what Brian saw may have been the
  selected row leaving the visible list, which `scrollIntoView` now fixes.
  Not confirmed.
- **Decisions link out and can be skipped.** Each candidate identifier
  links to doi.org or arxiv.org. Skip needs no backend change: the
  ambiguous file was already refused and the rest of the add went on.
- **Forms say required, optional, and what empty means.**
- **Settings page** in two parts: this window's preferences (cookies, as
  the theme is) and kennis's configuration (shared with cli and mcp,
  written through `engine/setup.py::apply_answers`). Every kennis setting
  carries when it takes effect. See #410.
- The traced wordmark is dropped for now (Brian: later); the plain serif
  word is back.

What I did not expect: the result-head and order control scrolled out of
the screenshot when a passage opened, because opening a long passage
moves the column; the real page may want the open passage scrolled into
view rather than leaving the reader where they were.
