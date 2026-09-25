# One group per collection

Milestone / step: v0.2.0 unit 0, concerns #229, #230, #231
Date: 2026-09-26

## What I am about to do

Stop printing search hits as one merged list, and print one group per
collection instead. This is unit 0 of the context milestone and it lands
before the bundle exists, because it fixes behaviour that ships in v0.1.1.

## How I expect it to work

Two defects, both reproduced on a real corpus with no context bundle
involved - index `notes` with `backend = none`, index `docs` with fastembed,
search both:

    [1] [docs]  relevance: very high   rrf=0.0328 bm25=0.23 cos=0.921
    [2] [notes] relevance: very high   rrf=0.0164 bm25=0.40

**#230.** Both levels say "very high" and neither means the same thing. The
docs hit is an absolute cosine; the notes hit is a fraction of the best BM25
in the list, and its own BM25 *is* that best, so it is very high by
construction. `_summary` then drops the basis phrase because the bases
disagree, which tells the reader least exactly where two scales share a
column.

**#229.** RRF sums `1/(k+rank)` over the legs that ranked a chunk, so a
two-leg collection scores double a one-leg one. The notes hit is rank 1 in
its own collection with the *better* BM25 and still comes second.

### The shape

    Found 5 in docs, 2 in notes

    Docs  relevance by cosine similarity
      [1] Fusion of rankings
          relevance: very high  id=othc40xf6u chunk=0

    Notes  relevance relative to the best lexical match
      [1] Why fusion uses ranks
          relevance: very high  id=30ed1x2rt8 chunk=0

The group heading is `display.operation(name.capitalize(), phrase)`, which is
the grammar `corpus status` already uses for a collection - a bold lead and
a plain rest. No new display primitive.

### What changes

- `_report` takes hits already partitioned by collection rather than one
  sorted list, and loops groups in `COLLECTION_NAMES` order. Fixed order,
  not ranked: ordering groups by quality would put the cross-collection
  comparison back in through the layout.
- `-k` applies **per collection**. Each group is a complete answer from its
  source rather than a truncated share of a blend.
- `_best_lexical` becomes per-group, which its own docstring says it wanted;
  the objection it records - that a per-collection best makes every
  collection's top hit "very high" - stops applying once each group carries
  a line saying its band is relative.
- `_summary` becomes counts per collection, `5 in docs, 2 in notes`, and
  loses the `len(bases) != 1` silence entirely.
- `hit_headline` drops its `collection` argument. The group heading carries
  it, and repeating it on every line is noise.
- Ranks restart at `[1]` in each group, because a rank is a position in a
  ranking and there is no longer one ranking.

### What does not change

The engine. This is entirely `cli/commands/search.py` plus two functions in
`render/hits.py`; `search()` still returns one collection's results and the
caller still calls it once per collection. #229's arithmetic is still wrong
for anything that compares fused scores across indexes, but after this there
is no such caller, so it gets a comment rather than a fix.

## What I expect to be uncertain or difficult

How many existing tests assert on the merged shape. The search tests are the
oldest part of the CLI suite and some of them will be asserting the thing
being removed - which is fine, but each one needs reading to tell "pinned
the old shape" from "pinned something that is still true and happens to be
phrased in terms of the old shape".

Whether `-k` per collection is surprising. `-k 5` on a three-collection
corpus can now return fifteen hits. I think it is right - a group truncated
to two because another collection was noisy is worse - but it is a change to
a flag people already use, and the summary line has to make the totals
obvious enough that nobody has to count.

The hint line at the end (`run kennis read X --chunks 0:2 to read one in
context`) names one hit. With groups there is no single best hit to name.
Probably the first hit of the first non-empty group, but that reads as a
claim that it is the best, which is what grouping exists to avoid.

## What actually happened that I did not expect


**Two of the first six tests were hollow, and the injections found both.**
Not "wrong" - they passed, they asserted something true, and neither could
fail for the reason it existed.

*Fixed group order.* The test gave `docs` the stronger match and asserted
`Docs` printed before `Notes`. But `COLLECTION_NAMES` already orders docs
before notes, so fixed order and quality order agreed and the assertion held
either way. Rewritten with the strong match in `notes`, so the two orders
disagree and only fixed order passes.

*Per-group lexical best.* There was no test at all, because I assumed the
change was covered by the tests that moved. Injecting `_best_lexical(everything)`
in place of `_best_lexical(hits)` went straight through. It needs two
collections whose BM25 magnitudes differ, which the old merged tests had no
reason to build.

**Ordering groups by the fused score is always a tie**, and I did not see
that until an injection failed to change anything. Every group's first hit
is rank 1 in its own collection, so its RRF score is `1/(k+1)` exactly,
whatever the collection. The injection sorted the groups by
`result.score` and the output did not move. That is #229's point arriving
from the other direction: the fused score carries no cross-collection
information *at all*, not merely biased information. A meaningful
quality-ordering injection had to sort on BM25 instead.

**`found[:wanted]` was dead code.** `search()` is called with `top_k=wanted`
and returns `_fuse(...)[:top_k]`, so the slice could never remove anything.
Written because "top_k per collection" felt like it needed enforcing
somewhere; the injection that removed it changed no test, which is what sent
me to look. Removed, with a comment saying why there is no slice.

**The hint line resolved itself.** The sketch worried that naming one hit
implies it is the best. It names the first hit of the first group, and with
the groups in fixed order that reads as "the first one printed" rather than
as a ranking claim - which is exactly what it is. No change needed.

**What the real corpus showed that the tests could not.** `-k 2` against
Brian's corpus now returns two irrelevant `literature` hits, banded `medium`
and `low`, *above* the genuinely good `docs` hit banded `high`. Both
consequences of the design as agreed - `-k` is per collection, and group
order is fixed - and both correct by that design. Whether it is what a
reader wants is a separate question, raised rather than decided here.
