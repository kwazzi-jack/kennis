# Milestone 3, step 4: building and publishing an index

Milestone / step: `design/plan.md`, "Milestone 3", items 2, 3 and 4.
Date: 2026-09-21

Previous sketch: `2026-09-21-m3c-loaders.md`. What it left: a corpus can be
read into documents, chunked, embedded and cached, and none of it is written
anywhere.

## What I am about to do

The build: read a collection, chunk it, embed what is not already cached,
write a self-contained index directory, publish it atomically, and record the
binding it was built with. This is where every piece from steps 1 to 3 is
finally wired to the others, and where the plan's remaining tests live.

## How I expect it to work

### The layout

```
<index root>/<collection>/
  latest.json              pointer, written AFTER the swap
  <index id>/              swapped wholesale
    chunks.jsonl
    bm25/
    embeddings.npy
    binding.json
    manifest.json
  vectors/                 the cache - a sibling, so the swap cannot reach it
```

The cache being a *sibling* of the index directory rather than a child is the
whole of its interrupt safety. `replacing_directory` replaces what it stages,
so a cache inside the index would be destroyed by the build it exists to make
cheap. Design section 15 states this and it is easy to get wrong by putting
files where they seem to belong.

`<index id>` is `{backend}-{model}` as boepie derives it, so switching model
and switching back does not destroy either index. It deliberately does *not*
encode the chunk parameters: `binding.json` is what detects that kind of
disagreement, and putting the whole binding in a directory name would
accumulate a directory per experiment.

### The order of work, and why each step is where it is

1. **Load.** `CollectionLoader.documents()`, reporting what it could not read.
2. **Digest and chunk**, per document. The digest is of the text; the chunks
   are deterministic given the text and the parameters, which is the property
   step 1 now has a test for.
3. **Refuse an empty collection before anything is written.** There are two
   distinct empty conditions and they deserve different messages: no
   documents at all, and documents that produced no chunks. `NothingToIndex`
   from step 1 covers the vocabulary case; this adds the earlier one.
4. **Ask the cache per document**, and embed only the misses. This is the
   plan's "adding one document and reindexing re-embeds one document, not all
   of them", and it is the only step that is new rather than ported.
5. **Stage everything**, then swap.
6. **Write the pointer after the swap, never before.** It is what makes an
   index findable, so publishing it over a directory still being written is
   the one ordering that could serve a half-built index.
7. **Prune the cache**, now that the current document set is known.

### Assembling the matrix

Chunks are ordered, and a rank is a position in that order, so the embedding
matrix must be in exactly the same order. Cached documents contribute their
stored rows; missed ones are embedded together in one call, because the
backend batches and a per-document call would lose that.

So the matrix is assembled by walking documents in order and taking either
the cached block or the freshly computed one. The invariant worth testing
directly: **row `i` of the matrix belongs to chunk `i` of the chunk list**,
whatever mixture of hits and misses produced it.

A cached block whose row count does not match the document's chunk count is
treated as a miss. That should be impossible - the digest and the parameters
are both in the key - but the failure it prevents is silent misalignment of
every subsequent row, and the check is one comparison.

### `binding.json`, and what it is for

Plan item 3: recorded "so `corpus status` can report that the configuration
and the index disagree rather than silently recomputing". It holds the
recorded form from step 2 - named fields plus the digest - so a person can
read why an index was rebuilt, and a program can compare without
reimplementing the hash.

This is concern #54's pattern, the one I want to copy rather than the one in
#50: a stored fact about the world that is **compared**, not trusted.

### The manifest

What was built, and over what: the chunk count, the time, and the document
identifiers with their digests. The digests are what a later staleness check
compares against the corpus, and they are the same digests the cache keys on,
so there is one notion of "this document's current text" in the system.

## What I expect to be uncertain or difficult

- **Proving the pointer is written after the swap.** The obvious test is a
  race. The testable version is to interrupt mid-build and assert the pointer
  still names the old index, which is the property that actually matters.
- **Interrupting a build in a test.** `replacing_directory` cleans up on an
  exception, so raising from inside the build is the lever - but the raise
  has to happen after staging has begun and before the swap, which means
  reaching inside the build to place it.
- **BM25 and the dense leg disagreeing about chunk order.** They are built
  from the same list in the same function, so this should be impossible by
  construction; I want a test that would notice if a later change broke it.
- **Whether `prune` should run when the build failed.** It should not - the
  document set is only known for a build that completed - but the code path
  is the same one.
- **An index built with no embedding backend at all.** boepie supports a
  lexical-only index and the plan does not mention one. I expect to support
  it, because the alternative is that a machine with no model cannot search
  at all, but it adds a None to every dense path.

## What actually happened that I did not expect

**I wrote a hollow test for the plan's own ordering requirement and only
found out by injecting the defect.** The plan asks that the pointer be
written after the swap, never before. My test interrupted the build during
embedding - which happens before staging begins - so publishing the pointer
immediately before `replacing_directory` did not fail it. It was testing that
the pointer is not written before *embedding*, which is a far weaker claim
than its name.

The general form is worth keeping: **a test for an ordering property has to
fail between the two events it orders.** Failing before both of them passes
for free. I had flagged "proving the pointer is written after the swap" as
the hard part in this sketch and then wrote the easy version anyway. Concern
#63, and the second half of the property - that a failure mid-staging leaves
the previous pointer untouched - was missing entirely until I looked.

**The interrupt-safety property forced embedding to go per document, which I
had not connected.** The sketch says vectors are cached per document; what I
had not noticed is that this only means anything if they are *embedded* per
document too. Vectors sitting inside one pending call for the whole corpus
cannot be written when that call is interrupted. So the cache's stated
property and the batch efficiency are in direct tension, and I chose the
property. Concern #64 names what that costs a hosted backend.

**My own test fixture fought the normalisation I added in step 2.** The
recording embedder encodes a text's length in its vector so row order is
observable; normalising `[n, n, ...]` yields the same unit vector whatever n
was, so the encoding was erased and the row-order test failed for a reason
that had nothing to do with row order. The fix is one flag, but it is the
third time in this project that a fixture has been the thing that broke -
concern #32's pattern, holding steady.

**`Binding.model` had to become optional and I had listed that as a
difficulty.** A lexical-only index is not in the plan and boepie supports
one. I kept it, because the alternative is that a machine with no model
cannot search at all. It cost a `None` in three places rather than the many I
expected, because the dense leg is already one branch.

**`mypy` caught a workaround for a circular import that did not exist.** I
had typed documents as `object` and reached for `getattr` and an
`assert isinstance`, on the assumption that importing `Document` into
`index.py` would cycle. It does not - `index` imports `loaders` imports
`models` - and the proper typing removed both hacks. I did not check before
working around it.
