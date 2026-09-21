# Milestone 3, step 1: the pure retrieval core

Milestone / step: `design/plan.md`, "Milestone 3", items 1 and 4 in part.
Date: 2026-09-21

Previous sketch: `2026-09-21-m2e-docs-and-fetchers.md`, which finished
milestone 2. What it left: all three collections can be populated, and
nothing can be searched.

## What I am about to do

Milestone 3 is 2,037 lines of boepie's `rag/` package, which is too much for
one unit of work, so it splits. **This step is the part with no network, no
model download and no disk layout**: the data models, the block-aware
chunker, and the BM25 wrapper - plus the empty-collection guard, which is the
plan's first test and belongs with BM25 rather than after it.

The intended split for the rest, recorded so the next session need not
re-derive it:

| step | what | why it is its own step |
|---|---|---|
| 1 (this) | `models.py`, `chunking.py`, `bm25.py` | pure and offline; testable in milliseconds |
| 2 | `embedding.py` and the vector cache | the first thing that downloads a model |
| 3 | `loaders.py` | the plan says this is the one needing real rewriting |
| 4 | `engine.py`: build, binding, atomic swap | needs all three above to exist |
| 5 | `search.py`: fusion, filters, ranking | needs an index to rank over |

## How I expect it to work

### The tree this adds

```
src/kennis/engine/rag/
  __init__.py
  models.py      # Document, Chunk, SearchResult, Filter. No I/O.
  chunking.py    # markdown -> Chunk spans with offsets. No I/O.
  bm25.py        # the lexical index, and the refusal to build an empty one.
```

`rag/` sits beside `corpus/`, `literature/` and `docs/` rather than inside
any of them: it is source-agnostic by design and knows nothing about
frontmatter, which is what lets the context bundle use the same engine later.

### Chunk parameters are a value, not a module constant

boepie reads `PROSE_CHUNK_SIZE` and `PROSE_CHUNK_OVERLAP` from `config.py` at
import time. kennis cannot, and the reason is the plan's item 2: the vector
cache is keyed on the **full derivation binding**, which includes the chunk
parameters, so they have to be a value something can hash rather than a
global something reads.

```python
@dataclass(frozen=True, slots=True)
class ChunkParameters:
    size: int = 1500
    overlap: int = 200
    version: int = 1
```

**`version` is not derivable from `size` and `overlap`**, and that is the
point of having it. Identical parameters run through a changed packing
algorithm produce different chunks, so a cache keyed on the numbers alone
would serve vectors for text that no longer exists. The version is bumped by
hand whenever the algorithm changes, which is a discipline rather than a
mechanism, and I would rather it be visible than clever.

This also settles concern #9 in the direction it was already leaning: kennis
threads its configuration as arguments rather than consulting globals. That
was an accident of testability in milestone 1 and is a requirement here.

### `models.py`

Ported close to whole: `Document`, `Chunk`, `SearchResult`, `Filter` with its
six operators, and `combine_filters`. `_lookup` follows a dotted path so a
filter can name `bib.year` or `docs.project`, which is exactly how kennis
frontmatter namespaces its per-collection block - the two were designed
against each other and the dotted path is why filtering will work at all.

These stay pydantic models rather than becoming frozen dataclasses like the
rest of the engine's value objects, and the reason is narrow: a `Chunk`
round-trips through the index on disk in step 4, so it needs validation on
the way back in. `Document` and `SearchResult` follow it for consistency
within the module.

`_glob_match` needs `globstar_regex`, which kennis already has in
`engine/_glob.py` from milestone 2's input resolution. Its rule that a
pattern matching a group also selects everything filed under it is kept: a
`--group calibration` that did not reach `calibration/gains` would be useless.

### `chunking.py`

Ported whole, with one change of shape. The chunker is block-aware: a
`markdown-it-py` parse with GFM tables and dollarmath locates atomic block
boundaries, and the packer never bisects one. Only prose is split, by a
sliding window snapped to the next whitespace within eighty characters so a
word is not cut in half.

Two details I want to carry over deliberately rather than by copying:

- **`_line_offsets` scans for `\n` rather than using `splitlines`.** Python
  breaks lines on `\x0b \x0c \x1c \x1d \x1e \x85`; markdown-it only breaks on
  `\n`. A form feed - which is exactly what a PDF-to-markdown page break
  leaves behind - would desynchronise the offsets from markdown-it's line
  numbers and silently misplace every block boundary after it. This is a
  one-line difference with a failure mode that would be very hard to find.
- **An oversized atomic block is kept whole**, so one over-long chunk beats a
  bisected table or a bisected display equation.

The change of shape: boepie constructs `Chunk(collection="")` and comments
"set by the index builder". A field that is a lie until someone remembers to
fix it is a defect waiting for a caller who forgets, so `chunk_document`
takes the collection as an argument and the chunk is correct when it is
built.

### `bm25.py`, and refusing to build nothing

`Bm25Index.build(texts)` tokenises with English stopwords, indexes, and maps
a retrieved rank straight back to a chunk by integer index - the whole
reason the chunk list stays ordered everywhere else.

The plan's first test says an empty collection must fail with a message about
the collection being empty, not with `max() iterable argument is empty` from
inside the vocabulary build. I checked this against the installed bm25s
0.3.11 rather than trusting the plan, and found two things the plan does not
say:

1. The `ValueError` is preceded by three `RuntimeWarning`s - `Mean of empty
   slice`, then two `invalid value encountered in scalar divide`. Under
   `filterwarnings = ["error"]` the *warning* is what a test sees, not the
   `ValueError`. So the guard has to stop the call from happening. Catching
   the exception would not work.
2. **A corpus of documents that are all stopwords fails identically.** The
   condition is not "no documents", it is "no tokens survived tokenisation".
   `["the and of"]` produces the same `ValueError` as `[]`.

So the guard checks the tokenised vocabulary, not the input length, and the
error is a new `NothingToIndex` naming `kennis corpus add` as its resolution.

## What I expect to be uncertain or difficult

- **`filterwarnings = ["error"]` meeting markdown-it and bm25s.** bm25s
  already emits three warnings on the path I am guarding; there may be others
  on paths I am not.
- **Whether `_sections` is correct.** It finds ATX headings with a regex over
  the raw text, while `_blocks` parses properly. A `#` comment at the start of
  a line inside a fenced code block looks exactly like a heading to a regex,
  and a Python file ingested as a code-fenced note is full of them. I suspect
  this is a real defect in the port and I want to know before I copy it.
- **Chunk identifiers assume a document is chunked once.** `f"{id}::{index}"`
  is only unique if the index is rebuilt wholesale, which item 4 of the plan
  says it is. If incremental chunk-level update ever arrives this breaks
  quietly.
- **`resolve_image_refs` touches the filesystem from inside the chunker**,
  which otherwise has no I/O. It checks whether each referenced image exists.
  That makes chunking untestable without a directory and makes the chunk
  content depend on the state of the disk at chunk time.
- **The boundary between "chunk parameters" and "chunker version"** may not
  survive contact with step 2's cache key, where I have to serialise it.

## What actually happened that I did not expect

**Both things I suspected before writing any code turned out to be true, and
one of them was worse than I described it.** That is a change from the last
six units of work, where the predictions were largely wrong (concern #32) and
the surprises came from fixtures.

The heading regex does read a `#` comment inside a code fence as a section.
What I had not worked out in the sketch is the second consequence: sections
are split *before* blocks are packed, so the fence is cut at those false
headings - the block-awareness that exists precisely to keep a code fence
whole is defeated before the packer ever runs. Taking headings from the same
markdown-it token stream fixes both and removes a parse rather than adding
one, which is the rare case where the correct version is also the cheaper
one. Concern #46.

**Checking the plan's claim against the installed library paid twice.** The
plan says an empty collection fails with `max() iterable argument is empty`.
It does, but three `RuntimeWarning`s fire first, so under `filterwarnings =
["error"]` a test sees `Mean of empty slice` instead - a guard that caught
the `ValueError` would not have worked. And the real condition is an empty
*vocabulary*, not an empty input: `["the and of"]` fails identically to `[]`,
because stopwords are removed before the vocabulary is built. Concern #47,
and a direct vindication of #33's habit of running a plan's pinned specifics
before depending on them.

**`bm25s.retrieve` pads its results to `k` with zero-scored entries.** I
found this writing the "a query matching nothing returns nothing" test, which
I had written expecting it to pass trivially. A query for a word not in the
vocabulary comes back as a full page of arbitrary chunks scored zero. Left
alone, reciprocal rank fusion in step 5 would give those real rank weight for
having matched nothing. Concern #48.

**`ANN401` and mypy strict wanted the same change, which I had read as two
problems.** `_lookup` returning `Any` let every caller use the value without
narrowing, and `Any` is also what ruff's `ANN401` forbids in a signature.
Returning `object` satisfies both and is the more honest type: metadata is
heterogeneous by design, so a value read out of it is not known to be
anything until it is checked. The comparison helper had to be rewritten to
narrow properly, and is clearer for it.

**My one prediction that did not materialise was the chunker's filesystem
access**, which I expected to make testing awkward. It did not - a `tmp_path`
and two files were enough. The concern I recorded about it (#50) is about
something else I noticed while writing that test: re-chunking the same text
after an asset moves produces different chunks, and the vector cache will not
notice, because it is keyed on the document digest and the text has not
changed.

**One test of mine was simply wrong.** I asserted that a document of headings
with empty bodies produces no chunks. A heading is content - `# Calibration`
with nothing under it is worth retrieving, and dropping it would lose the
only text in that section - so the behaviour is right and the test was not.
Corrected, and the decision is now stated in a test of its own rather than
left implicit.
