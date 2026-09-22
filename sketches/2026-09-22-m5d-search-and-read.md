# Milestone 5, step 4: `kennis search` and `kennis read`

Milestone / step: `design/plan.md`, "Milestone 5", item 2.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5c-the-mutating-commands.md`. What it left: the
whole of `kennis corpus`, the lock, the log, and an index that nothing reads.

## What I am about to do

The two commands that read the index milestone 3 built. `search` ranks
chunks across the collections that have an index; `read` shows what
surrounds one hit.

This is the last thing v0.1 needs to be usable: a person can add documents,
index them, search them, and read the results.

## How I expect it to work

### A sweep is the default, and a named collection is a promise

Ported from boepie, whose reasoning is worth keeping verbatim in effect:

| asked for | index missing | what happens |
|---|---|---|
| no `--collection` | one of several | skipped, and said so |
| `--collection docs` | that one | the command fails |
| either | present but unreadable | the command fails |

The asymmetry is the point. A collection you never mentioned is simply not
part of the answer; the one you named is what you asked for, and answering
"no hits" when the truth is "never indexed" is the failure this exists to
prevent. Anything other than a missing index stops the run even in a sweep,
because silently dropping a collection the user believes was searched is the
same failure wearing a different hat.

### Fusing across collections, and why it is not a second fusion

`search()` returns results whose scores are already reciprocal rank fusion
over one index's two legs. Merging three collections means ordering by that
score, which is defensible precisely because RRF scores are functions of rank
rather than of any collection's score distribution: `1/(k+rank)` means the
same thing in literature as in notes, where a BM25 score does not.

Each hit is labelled with its collection, so a merged list stays readable as
three lists that happen to be interleaved.

### Falling back to lexical, loudly

An index built with no embedding backend has no dense leg, and `search`
raises `SearchUnavailable` for `hybrid`. Refusing would be wrong: #96 means
a fresh install may well have a lexical-only index, and requiring
`--mode bm25` on every search would be a flag people alias away.

So a hybrid search against a lexical-only index runs as BM25 and **says
so**. Saying so is the whole of it - a silent downgrade would have people
comparing result quality against a dense index they do not have.

### `read` is the companion to a hit, not a second `cat`

`read_span` stitches the chunks around one chunk back into a continuous run.
That is what a reader wants after a search - the hit plus its surroundings -
and it is why this reads from the index rather than from the file. A command
that printed the file would be a different command, and the document is
already at a path the search output names.

### What comes from where

Every sentence from `render/`, per #81. A hit's layout - the score column,
the snippet indent, where the collection label sits - is `cli/`, and what a
score *means* is neither: it is a number the engine computed.

## What I expect to be uncertain or difficult

- **Snippets.** boepie has `none|short|full`. Truncating a chunk mid-word is
  the obvious trap, and truncating mid-sentence is the less obvious one.
- **Whether `--group` belongs in v0.1.** boepie filters by a shell-style
  group pattern and aliases `--project` to it for docs. The filter machinery
  exists (`Filter`, `combine_filters`), so the cost is the option surface
  rather than the mechanism.
- **The embedder for a dense query.** `search` embeds the question with the
  *index's* binding, read back from disk, not the caller's configuration.
  The CLI must not pass its own, and I expect the temptation to.
- **`read` without an index.** `read_span` raises naming `kennis index`,
  which is right, but the document is sitting on disk and a user may
  reasonably expect to see it. Whether that is a second command or a
  fallback is undecided.
- **Testing a dense search offline.** Every test so far has used
  `KENNIS_EMBEDDING_BACKEND=none`. Exercising the hybrid path needs a stub
  embedder reachable from a command, and the command deliberately does not
  take one.

## What actually happened that I did not expect

**Five of the first thirteen tests were hollow, and the injections found all
five.** They passed, and every one of them passed for a reason unrelated to
what it claimed.

| test | passed because |
|---|---|
| a hit names its collection | `"notes"` also appears in the lexical-fallback warning |
| no hits is not a failure | `"no" in output` matches "notes" and "no dense leg" |
| naming an unindexed collection fails | nothing at all was indexed, so it failed one step earlier |
| top-k bounds the answer | only one collection was indexed, so the final cut is unobservable |
| top-k, again | `fewer than` would pass for a command that always returned one |

Two patterns worth naming. **A bare substring is not an assertion about a
line**; hits are now counted by `[<collection>]`, a bracketed label that
appears on a hit line and nowhere else. And **a test of a promise must fail
only when the promise is broken**: "the collection you named must fail" was
satisfied by the corpus having no indexes at all, so it now indexes notes
first, which is the only arrangement where the promise is the thing under
test. That is #63's rule about ordering, generalised - failing for a reason
that precedes the behaviour passes for free.

**Running the command found two things no test would have.** The first hit
printed `[notes] Rivers - Rivers`, because a short document's only heading is
its title and the section duplicated it. The second was three separate
warnings about unindexed collections above a one-line answer, which on a
corpus with only notes indexed is two thirds of the output before the result.
Both are `render/` and `cli/` decisions that are correct in the parts and
wrong in the whole, which is the kind of thing only reading the output
catches.

**The lexical fallback earns its warning.** With `backend = "none"` the
default `hybrid` would otherwise raise `SearchUnavailable` on a corpus that
is perfectly searchable, so a fresh install would meet an error on its first
search. Falling back silently would be worse than either. This is #96 and
#103 showing up in a third place, and it is the argument for the setup wizard
made concrete: a user who has chosen their backend never sees this line.
