# Realigning the workbench, 2: the shell holds still and says where things stand

Milestone / step: milestone 11 realigned with the approved mockup (#447)
Date: 2026-10-12

## What I am about to do

Three things the mockup and plan 11a/11b settle and the window does not
do:

1. Only the centre pane scrolls. Following a link to a passage scrolled
   the page itself, so the bar left the window and a band of ground
   showed under the strip.
2. The idle strip says what the plan lists: the corpus's commit, what is
   searchable, what needs indexing, and the last change. It says only
   the second now, plus the last job of this launch.
3. The pane carries the corpus's total, a legend for the dots, and the
   Packs and Settings places.

## How I expect it to work

**Scrolling.** Measured first in the headless shell. `html` reported a
scroll height of 37,647px against an 860px viewport, so the page itself
overflowed. Something positioned absolutely inside `main` (the visually
hidden labels) was placed against the initial containing block, at its
position in the document. `main { position: relative }` makes the pane
their containing block, so its own `overflow` clips them. Checked by
measuring again; a CSS test keeps the declaration.

**The strip.** The last change comes from the corpus's own history,
because that survives a restart and covers the command line as well.
`Repository.last_commit()` runs one `git log -1` and returns a
`Commit(sha, when, operation, scope, summary)`. The subject is parsed as
`operation(scope): summary`, the form `Repository.commit` writes, and
taken whole as the summary when it does not match. That is a fact
recorded at commit time; the words are the window's. `holdings.
last_change(context)` is the front end's way to it. What needs indexing
is counted per collection: `added + changed` when it has an index, every
document when it has none. `PaneCollection.waiting` carries it. The
link to the last job of this launch stays, because it leads to that
job's outcome.

**The pane.** The Corpus heading gains "N documents". The kennis section
gains Packs (`/corpus#packs`, with the installed count) and Settings
(`/settings`). A legend under the sections says what the two coloured
dots mean, in the words `PANE_STATES` already holds.

## What I expect to be uncertain or difficult

- A commit's time is the committer's, so a clock that is wrong on
  another machine shows as a wrong "ago". Accepted.
- Whether the strip, which is one line, still fits at narrow widths with
  four items. It wraps (`flex-wrap`); check at 600px.
- The pane is on every page, so another `holdings` call per page is not
  wanted. `pane_now` already calls it once, and the strip reads the pane.

## What actually happened that I did not expect
- **The parser already existed.** `read_history` in
  `engine/history/history.py` parses `operation(scope): summary` and
  keeps a hand-written subject whole, for `corpus history`. I had
  written tests for a `Repository.last_commit()` before looking. They
  were deleted, and `holdings.last_change` calls `read_history(limit=1)`.
  The sketch named the dataclass and the parse rule as if both were new.
- **One injection was missed, and the test was not hollow.** The strip
  test added a note to a collection that had never been indexed, so it
  never reached the "added or changed since an index" branch. A second
  test indexes, then adds, and asserts one document waits.
- **Packs and Settings went into the palette too**, because the palette
  lists every place and a place in the pane that the palette lacks
  would be a gap between two lists of the same thing. The hand-written
  palette expectation gained both. "Packs" was a literal in
  `corpus.html`; it is `PACKS_HEADING` now.
- My first pane test fetched the page without the launch token and read
  the refusal. Every other test in the file calls `admitted(client)`.
- Walked on Brian's corpus at 1280px in both themes and at 600px. The
  page's scroll height equals the viewport, the dots resolve to the
  added and warning colours in both themes, and the strip wraps to two
  lines at 600px. Nothing on his corpus waits, so the warning item was
  correctly absent; the tests cover it.
- Injections: ten, all caught after the second strip test.
- The mockup's strip has a commit icon and a warning icon; neither is
  vendored, and the strip is text only. Not worth two more icons yet.
