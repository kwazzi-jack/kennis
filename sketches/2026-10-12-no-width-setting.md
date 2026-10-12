# The vector width is not a setting (Brian, 2026-10-12)

Milestone / step: following #441 and #445
Date: 2026-10-12

## What I am about to do

Remove `embedding.dimensions`. The width of a vector is fixed by the
model, no backend is sent it, and nothing compares it with the vectors.
As a setting it can only be right by agreement, and wrong in silence.
Brian: "Probably something we can remove then."

## How I expect it to work

The width reaches four places, and each loses it:

- `EmbeddingSettings.dimensions` and the `BackendModel.dimensions`
  column of `EMBEDDING_DEFAULTS`. The table keeps the model.
- The catalogue: the three `embedding.dimensions` questions,
  `_suggested`'s width branch, `setting_costs`, and the window's name
  for it.
- `ModelBinding.dim` and `embedding_dim` in `binding.json`. The model
  name identifies the width already, so the identity loses nothing it
  needs.
- The two empty shapes. `embed_texts([])` returns `(0, 0)`, and
  `_vectors_for` stacks only the blocks that have rows. An empty block
  adds no rows, so row `i` is still chunk `i`. An index with no vectors
  is `(0, 0)`, and `search.py:276` already returns early on zero rows.

**An existing index stops matching its configuration.** The recorded
binding's digest included `embedding_dim`, so every index built before
this reports as built with other settings, and the vector cache, keyed
on the same derivation, misses. One `kennis corpus index` rebuilds each.
No compatibility before v1.0.0 (#445). A `binding.json` that still
carries `embedding_dim` is read without it, because `from_recorded`
reads named fields and ignores the rest.

A `config.toml` that still holds `dimensions` loads as before, because
the section model ignores an unknown key. The next write drops it,
because every write now renders the model's own keys (#445).

## What I expect to be uncertain or difficult

- What a stale binding looks like to Brian: whether search still runs,
  and what `corpus status` says. To be measured on his corpus, read-only,
  after the change.
- Tests that construct `ModelBinding(dim=...)` in about a dozen files.
  This is mechanical, but one test in `test_binding.py` asserts that a
  width change misses the cache. That property goes with the setting.
- Whether a fake embedder in the tests returns a width that some
  assertion compares with `binding.dim`.

## What actually happened that I did not expect

- **Nothing on Brian's corpus went stale for searching.** The sketch
  expected every index to report itself as built with other settings. It
  did not. `corpus status` compares documents, not bindings, and said all
  three were in step. A search ran normally, because `from_recorded`
  reads named fields and skips `embedding_dim`, and the query side
  compares the model, not the digest. The one cost is the vector cache,
  which is keyed on the derivation digest. The next `kennis corpus index`
  embeds every passage again, once.
- **The empty case had a second reason to change.** Measuring the width
  would have meant asking the model to embed something, which for a
  hosted backend is a request with no text in it. The empty block is
  `(0, 0)` and asks nothing, and a test asserts that the embedder was
  not called.
- One test in `test_binding.py` asserted that a width change misses the
  cache. It became the assertion that no recorded field and no setting
  names a width.
- Injections: four, all caught. Re-adding the question fails more
  broadly than intended, because the field no longer exists and every
  call to the catalogue raises.
