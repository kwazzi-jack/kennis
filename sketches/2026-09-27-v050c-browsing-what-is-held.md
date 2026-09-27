# v0.5 unit 9c: browsing what is held, and the view that goes stale

Date: 2026-09-27

## 1. What I am about to do

A window onto `corpus status`, `corpus list`, `corpus tree` and
`pack list`: which collections exist, how much is in them, how far
each index has fallen behind, and which packs are installed.

And the thing the plan said would present itself here: a view that
was true when it was drawn. Concern #311.

## 2. How I expect it to work

**Nothing is added to the engine.** Every answer already exists as a
typed value - `Collection.contents()`, `index_freshness`,
`list_installed` - and `render/words.py::describe_freshness` and
`render/packs.py::describe_holdings` already phrase two of them. This
unit adapts.

**The freshness orchestration is shared, not repeated.** Reading the
manifest and calling `index_freshness` is four lines with a subtlety
in it - `indexed=manifest.documents` must be passed, or every `kennis
remember` reports the note it just indexed as unindexed (concern
#245). A second copy in the interface is a second place to omit that.
So it moves to `kennis/holdings.py`, beside `context.py` and
`retrieval.py`, for the reason #292 gives and #314 warns about.

**Staleness is answered lazily, and this is the decision #311 left
open.** Every page recomputes on request, so nothing a person just
asked for is stale. The only stale thing is a window left open while
a terminal writes to the corpus.

For that: the page carries the revision it was drawn at -
`Repository.head()`, one `git rev-parse` - and asks again when the
window regains focus. **No timer.** A timer spends a subprocess a
minute forever to answer a question nobody asked; focus is the moment
the answer starts mattering, and it costs nothing while the window is
in the background. #311 rejected polling and this is what it leaves.

A corpus with no commits answers `None`, which is not an error: a
fresh `corpus init` has none until something is added.

## 3. What I expect to be uncertain or difficult

- Whether `Repository.head()` is cheap enough to call per request. It
  shells out to git, and `corpus status` already does far more, but
  every page would now pay it.
- What to show for a collection whose index has never been built. The
  command line says nothing and moves on; a table has a cell to fill.
- Whether `describe_freshness` reads sensibly out of its line-oriented
  context. It was written for a detail line under a heading, and a
  table cell is not that.
- Whether grouping documents by their directory is worth doing here or
  is `corpus tree`'s job and belongs in a later unit.

## 4. What actually happened that I did not expect

**Two of eight injections were not caught, and they failed for
opposite reasons.** One found a real gap: nothing anywhere exercised
`Holding.unreadable`, so setting it to zero passed. The other was a
bad injection rather than a hollow test - I added `dependencies=[]` to
a route, which does nothing at all against a guard implemented as
middleware, so the behaviour never changed and the test was right to
pass. Replacing it with a real exemption inside the middleware, it is
caught.

That distinction is worth keeping separate from #312. There the
verdict was read from the wrong signal; here the *change* was inert.
An injection that does not alter behaviour is indistinguishable from a
defect the tests catch, and the only defence is knowing the mechanism
well enough to break it on purpose.

**The collection order is `literature, docs, notes`**, not the
`notes, literature, docs` I wrote into a test from memory. The code
was right - it iterates `COLLECTION_NAMES` - and the test now asserts
against that tuple rather than a list written beside it, because a
list written beside it is the second place that has to change.

**`describe_freshness` reads well in a table cell but says the
collection name twice.** Section 3 doubted it would transfer from a
line-oriented report; it does, producing "the literature index is in
step, with 1 document not yet indexed". In a table whose first column
is already `literature`, the prefix is redundant. Left alone and
logged as #316: it is shared wording, the command line needs the name
because its lines have no column to carry it, and changing it for one
front end is how shared wording stops being shared.

**Staleness settled more cheaply than #311 feared.** Every page
recomputes on request, so the only stale thing is a window left open -
and the answer to that is one `git rev-parse` asked when the window
regains focus. No timer, nothing running while the window is in the
background, and no corpus walk. #311 said the wrong answer was a
timer and did not say what the right one was; focus is the moment the
answer starts mattering.

**Live against the real corpus**, the holdings page reports 3
literature, 45 docs and 4 notes, names two installed packs, and
carries a 40-character revision that the endpoint agrees with.
