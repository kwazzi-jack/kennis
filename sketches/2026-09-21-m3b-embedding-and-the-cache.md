# Milestone 3, step 2: embedding backends and the vector cache

Milestone / step: `design/plan.md`, "Milestone 3", item 2.
Date: 2026-09-21

Previous sketch: `2026-09-21-m3a-chunking-and-bm25.md`. What it left: text can
be cut into chunks and searched lexically, and nothing can be embedded.

## What I am about to do

Two pieces that the plan lists as one item: the embedding backends, and the
cache that stops a rebuild re-embedding documents that have not changed.

**The plan calls milestone 3 "the part that is ported rather than rewritten".
That is true of step 1 and false here.** boepie has no vector cache: its
`build()` calls `embed_texts` over every chunk every time, and the document
digests in its manifest are used to detect staleness, never to reuse work.
The plan's own test for this item - "adding one document and reindexing
re-embeds one document, not all of them" - describes behaviour that does not
exist upstream. So the backends are a port and the cache is new code, and I
would rather say so than discover halfway that I am looking for something
that was never there.

Design section 15 does specify it, in detail, and is what I am building to.

## How I expect it to work

### The tree this adds

```
src/kennis/engine/rag/
  embedding.py   # ModelBinding, the three backends, embed_texts
  binding.py     # the full derivation binding and its digest
  cache.py       # vectors on disk, keyed by that binding
```

`binding.py` is separate from both because two unrelated things need it: the
cache keys on it, and step 4 writes it to `index/binding.json` so `corpus
status` can report that the configuration and the index disagree.

### The binding is the whole derivation, and nothing less

Design section 15 is explicit, and explicit about why the obvious shorter key
is wrong:

```
(document_id, document_digest, chunker_version, chunk_params_digest,
 embedding_backend, model, dimensions, normalisation) -> vectors
```

The failure it prevents is worth restating because it is silent. Key on
content and model alone, then change the chunk size: every document is a
cache **hit**, so the dense index is reused over the *old* chunk boundaries
while BM25 is rebuilt over the *new* ones. The two indexes then disagree about
what chunk number seven is, and every hit offset, read span and fused rank is
computed against mismatched lists. Nothing errors. The results are merely
wrong, and plausibly so.

So `Binding` carries the chunk parameters and the model binding together, and
its digest is what the cache keys on. Any change to how a vector is derived
is a total miss, with no flag and no special case.

### Determinism stops being an assumption

Section 15 says this in as many words: "Determinism becomes a requirement with
a test - same content and same parameters produce the same chunk list byte for
byte - not an assumption about existing code." The whole cache rests on it, so
step 1 gets a test it did not have: chunk the same document twice, and again
from a fresh parse, and assert the spans and texts are identical.

### `embedding.py`

`ModelBinding(kind, model, host, dim, normalise, max_async)`. Three backends:
`fastembed` by default because it runs a small ONNX model on CPU with no
server, no API key and no network after a one-time download; `ollama` and
`openai` for anyone who already has that infrastructure, with `host` doubling
as an OpenAI `base_url` override so a local vLLM or TGI works through the same
path.

Two departures from boepie, both deliberate.

**It presents a synchronous interface**, because design section 20 says the
engine does and only the fetchers hide concurrency inside. boepie is `async`
all the way down.

**Concurrency is a thread pool, not an event loop.** boepie uses
`asyncio.gather` with a semaphore, and `fastembed` is then pushed *back* onto
a thread with `asyncio.to_thread` because ONNX inference is CPU-bound and
blocking. A bounded `ThreadPoolExecutor` with the synchronous clients gets the
same bounded concurrency for the network backends, needs no event loop for
the local one, and lets the whole module be called from anywhere. Row order
is restored by index rather than by completion order, exactly as boepie does.

**`normalise` is new.** The plan's binding names normalisation and boepie's
`ModelBinding` has no such field - it relies on whichever models happen to
emit unit vectors. kennis normalises explicitly when the flag is set, which
makes cosine similarity a plain dot product in step 5 and, more importantly,
makes the flag mean something so that recording it in the binding is not
decoration.

### `cache.py`

A dict persisted to disk, which is what section 15 says it is - not a vector
database, and the section argues that case at length so I will not reopen it.

- **Keyed per document, not per chunk.** A document's chunks are determined by
  its text and the chunk parameters, both of which are in the key, so one
  entry holds the whole document's matrix.
- **Stored outside the swapped index directory**, because it has to survive
  the swap. `replacing_directory` replaces what it stages; a cache inside it
  would be destroyed by the very build it exists to make cheap.
- **Written per document**, so an interrupt loses at most the in-flight
  document's vectors rather than the run.
- A build that aborts leaves cached vectors for an index that was never
  published. Section 15 says that is harmless and is the point.

Layout: one `.npy` per key under a cache root, named by the key digest, with
the binding recorded alongside so the directory is readable rather than a pile
of hex.

**Pruning**: section 15 leaves it open. I am implementing `prune(keep)` and
not calling it yet - step 4's build is where the set of current documents is
known. Offering the method without wiring it is the smaller commitment, and
the decision stays visible rather than defaulting to unbounded growth by
omission.

### The model download is a reported step

Section 15 asks for this specifically: the first embedding on a machine
fetches the model, 33 seconds on the measurement recorded there, inside what
would otherwise look like a hung line. The engine does not print, so it emits
the event and a front end renders it.

## What I expect to be uncertain or difficult

- **Testing without downloading a model.** Every test must run against an
  injected backend. If the seam is in the wrong place this becomes obvious
  immediately, which is the good case.
- **`fastembed` 0.8 against the plan's `>=0.5` floor.** The same shape as
  concern #33, and the same shape as bm25s in step 1, which did bite.
- **What the cache stores for a document with no chunks.** An empty matrix
  and a real entry, or no entry at all? The difference shows up as repeated
  work on every build for a document that will never produce chunks.
- **`dim` is `None`-able in boepie's binding and required by the cache**,
  which has to shape an empty matrix. I expect to make it required and find
  out why boepie did not.
- **Whether the digest should include the chunker's own source.** `version`
  is bumped by hand (step 1's decision), and a bug fix that changes chunk
  boundaries without a bump is exactly the silent failure the binding exists
  to prevent. I do not have a better answer than discipline, but I want to
  have looked at it.

## What actually happened that I did not expect

**The thing I flagged in the first paragraph was the most valuable part of
the sketch, and I nearly did not check it.** I wrote that the plan's "ported
rather than rewritten" is false for this item, having read `build()` and seen
`embed_texts` called over every chunk. Had I trusted the framing instead, I
would have spent the session reading `rag/engine.py` for a cache that was
never there. Concern #55, and the same shape as #33 one layer up: a plan's
description of inherited code goes stale, and the cheapest moment to check is
before depending on it.

**Three of my five predicted difficulties did not materialise, and the two
that did were both typing.** fastembed 0.8 against the `>=0.5` floor was
clean, which I recorded as concern #59 precisely because #33 is a habit and a
habit needs its misses on the record as well as its hits. Testing without
downloading a model was trivial once the `Embedder` protocol existed - which
is what the prediction was really about, and the seam turned out to be in the
right place first time.

**fastembed ships type information, which I had assumed it would not.** It is
the first backend in this project that does. Its `embed` takes `documents`
and returns an iterable of arrays rather than a matrix, so it does *not*
satisfy a natural `Embedder` protocol, and mypy said so precisely. The
loaded-model cache is typed as `TextEmbedding` under `TYPE_CHECKING`, keeping
the runtime import lazy. My prediction that the untyped-package override list
would grow was wrong in the useful direction.

**`dim` being optional in boepie turned out to have no defence.** I predicted
I would "find out why boepie did not" make it required. There is no reason
visible in the code: `dim` is `int | None`, `build()` raises `ValueError` if
it is None, and every other use assumes it. Making it required moves that
check from runtime to construction and deletes the raise.

**The zero-vector `nan` was predicted and prevented rather than found.** I
wrote the guard and the test together, so it never appeared as a bug. Worth
noting because it is invisible in the outcome: `nan` does not raise, compares
false against everything, and would have quietly removed a chunk from every
result set. This is the class of thing concern #48 was, one step earlier.

**Design section 15's open question had a second half it did not state.** It
asks whether the cache is pruned, and frames it as removed documents leaving
vectors behind. The faster growth in ordinary use is the other one: a
document *edited* several times leaves one cache entry per version it ever
had. `prune` handles both. Concern #58.

**Two mistakes of my own, both in a file the tests passed on.** I wrote
`type ProgressCallback = "Callable[[int, int], None]"` as a string alias,
defined after its use and with `Callable` never imported, and referenced a
`_TextEmbedding` name that did not exist. All seventeen embedding tests
passed with both present, because neither is evaluated at runtime under
`from __future__ import annotations`. mypy caught both. That is the clearest
argument I have yet seen in this project for the type gate being part of the
loop rather than a formality: a green test suite said nothing about either.
