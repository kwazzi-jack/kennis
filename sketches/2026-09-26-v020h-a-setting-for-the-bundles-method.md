# A setting for the bundle's method

Milestone / step: v0.2.0 unit 7
Date: 2026-09-26

## What I am about to do

`retrieval.context_method`, defaulting to `bm25`. Unit 3 hardcoded
`model=None` with a comment naming this unit; this is where the hardcoding
becomes a decision the user can make.

## How I expect it to work

One field beside `corpus_method`, the same three values, a different
default:

    corpus_method   hybrid | bm25 | dense   default hybrid
    context_method  hybrid | bm25 | dense   default bm25

The default is the design's, not a shrug: a hybrid bundle index would turn
`context init` from an offline scaffold into a 65 MB model download, and
design section 19 adds that a model-specific bundle index makes the
cross-machine binding match much less likely, which is what committing the
index is for.

Three places read it.

**`context index`** builds a lexical binding when the setting is `bm25` and
`binding_from(chunking, embedding)` otherwise. `binding_from` already
answers `model=None` for `embedding.backend = "none"`, so asking for hybrid
on a machine with no backend is a lexical index rather than a failure - the
same behaviour the corpus has.

**`search`** takes its `asked` mode per scope rather than once: context asks
`context_method`, a corpus collection asks `corpus_method`, and an explicit
`--mode` overrides both.

**`_fallback`** loses the special case unit 4 added. That case suppressed
"the context index has no dense leg" because a bundle is lexical by design -
but with `asked = "bm25"` the function short-circuits before the note, so
the suppression becomes dead. And when someone *has* set `context_method =
hybrid` and the index is lexical, the note is exactly right and must print.
A special case replaced by the mechanism that made it unnecessary.

## What I expect to be uncertain or difficult

Whether `index_bundle` should take a `Binding` instead of `chunking` plus a
new `model`. The binding is what it uses, so passing it whole is the honest
signature; against that, the engine's default should stay lexical, because
that is the bundle's nature rather than a caller's preference, and a
required `binding` argument states nothing while churning every test.

Whether a bundle index built as hybrid breaks the clone promise quietly. It
does, and the design says so - but nothing warns at the moment the setting
is changed, and the person who set it is not the person who clones.

## What actually happened that I did not expect

**The special case removed itself, which was the point and still surprised
me.** Unit 4 suppressed "the context index has no dense leg" with an
explicit `if name != CONTEXT_COLLECTION`. Once the mode asked for a bundle
is `bm25`, `_fallback` short-circuits before the note is reached, so the
suppression is dead code - and when someone sets the method to hybrid and
gets a lexical index, the note is exactly the sentence they are owed. A
setting that replaced a special case with the absence of one.

**Two tests passed with the setting ignored.** The first asked `context
index` whether the setting was read, and on a machine with no embedding
backend both answers produce an identical lexical index, so the command
cannot tell them apart - the test was asserting something true of both
branches. Fixed by naming the policy, `context_model(settings)`, and asking
it directly, with `ollama` as the backend because building a `ModelBinding`
for it reaches nothing at all: no download, no daemon, no network. The
second gap was the mirror: nothing asserted that a *corpus* collection still
uses `corpus_method`, so the two settings could have been swapped with a
green suite.

That is the third time this milestone that a behaviour only observable
through a whole command turned out to be untestable through it. Naming the
decision is what fixed it each time.

**The signature question answered itself in favour of defaults.** A required
`binding` argument would state nothing a reader does not already know and
would churn every call site; `model=None` as the default says the bundle's
nature in the place it is true, and the front end resolves the setting
because nothing under `engine/` reads settings (#87).

**The clone warning is still not written.** Setting `context_method =
hybrid` makes the committed index model-specific and quietly breaks the
clone-and-go promise for anyone whose configuration differs. The design says
so; nothing says it at the moment the setting is changed, and the person who
sets it is not the person who clones. Logged as #246.
