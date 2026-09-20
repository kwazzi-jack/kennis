# Milestone 1: documents on disk

Milestone / step: `design/plan.md`, "Milestone 1", all five items.
Date: 2026-09-20

Previous sketch: `2026-09-20-m0-scaffold.md`. What it left: an engine holding
only `errors.py` and `events.py`, a working `cli/display.py`, architecture
tests that fail if the engine imports an interface, and a `Recorder` sink no
operation emits into yet.

## What I am about to do

Give the engine a corpus: the frontmatter schema, surrogate identifiers
derived from the natural key, reading and writing one document atomically, and
a collection that can be walked and resolved against. No search, no git, no
command line.

## How I expect it to work

### The tree this adds

```
src/kennis/engine/
  _atomic.py             # ported from boepie, unchanged in substance
  frontmatter.py         # the YAML-frontmatter codec
  corpus/
    __init__.py
    schema.py            # the pydantic frontmatter models
    ids.py               # surrogate identifiers
    layout.py            # the directory rules and the store root
    document.py          # read, write, move, remove one document
    collection.py        # walk a collection, resolve an identifier
```

Two files sit at `engine/` rather than under `corpus/`. `_atomic.py` is where
the plan puts it. `frontmatter.py` follows it for the same reason: the context
bundle will read and write frontmatter too, and a codec living inside `corpus/`
that `context/` reached back for would close an import loop. The plan does not
name it because boepie's copy lives in `context/`, which is the direction the
dependency would be wrong in here.

### `engine/corpus/schema.py`

`DocumentFrontmatter` is the base: `id`, `title`, `owner`, `source`, and the
optional `id_from`. Then `NoteFrontmatter` (adds nothing), `LiteratureFrontmatter`
(adds `bib`), `DocsFrontmatter` (adds `docs`). `extra="forbid"` on every model,
so a key kennis does not understand is an error rather than a silent drop.

Named apart from boepie deliberately: boepie has `CorpusDocument` twice, once
as the pydantic model and once as the on-disk record, and they are different
things. Here the models are `*Frontmatter` and the record is `Document`.

Three changes from boepie's schema:

- **`owner` replaces `managed_by`**, per design section 6. The value is `user`
  or `pack:<id>`, validated by pattern. Anything else - including the old
  `boepie` - is refused with the document named. No migration, no fallback to
  `user`.
- **`id_from` is new**, and carries the natural key the identifier was derived
  from: `arxiv:1101.1764`, `doi:10.1088/...`, `bibcode:...` or
  `docs:numpy/quickstart`. Design section 19 requires the derivation input be
  recorded "so it is auditable rather than guessable". Absent means the
  identifier was minted at random, which is the note case and the only case.
  The invariant a checker can then apply: if `id_from` is present,
  `derive_id(id_from)` must equal `id`.
- **`source.from` keeps its pydantic alias.** Section 7's "no aliases
  anywhere" is a rule about `.ken.yml`, and `from` is a Python keyword, so a
  field of that name is not expressible. Section 4 writes the key as
  `source.from`, so the alias is what makes the design's own spelling
  possible rather than a deviation from it.

### `engine/corpus/ids.py`

Ten characters over lowercase letters and digits, as boepie mints them. What
changes is where they come from.

```
derive_id("arxiv:1101.1764") -> the same ten characters on every machine
mint_id(existing)            -> ten random characters not already taken
```

`derive_id` hashes the key with `blake2b(digest_size=16)`, reads the digest as
an integer, and writes it in base 36 over the alphabet, taking the low ten
digits. blake2b rather than sha256 because the digest size is a parameter
rather than a truncation, and the stdlib has it.

The key is namespaced by its kind before hashing - `arxiv:`, `doi:`,
`bibcode:`, `docs:` - so a DOI that happens to spell an arXiv identifier
cannot collide with it. Precedence for literature is arXiv identifier, then
DOI, then bibcode; for docs it is `project/page`; notes have no natural key
and get `mint_id`.

The constraint underneath: **derived from identity, never from content.**
Hashing the body would change the identifier on every edit, which is the exact
failure a surrogate exists to prevent. Two of the plan's tests are this
constraint stated twice - editing the body and retitling both leave the
identifier alone - and they pass trivially because nothing in the derivation
input mentions either. That is the point; they are regression tests against a
future change that reaches for the body.

`derive_id` is frozen at creation. If later enrichment finds a
higher-precedence identifier, it is added to `bib` as an ordinary field and
the identifier does not move.

### `engine/corpus/layout.py`

Ported from boepie with the walking rule intact: a `.md` file is a document; a
directory holding `content.md` is a document with assets; any other directory
is a group. Dot-prefixed names and non-markdown files are bookkeeping and are
skipped. Filenames are the full title with filesystem-illegal characters
stripped, collision-suffixed `(2)`, `(3)` collection-wide.

Added here: `default_corpus_root()`, which is `platformdirs.user_data_dir("kennis")`,
and `collection_root(root, collection)`. Every function that touches disk takes
the root as an argument, so a test passes `tmp_path` and nothing reads the real
store. Settings arrive later and will supply the root; until then the default
is the only source.

### `engine/corpus/document.py`

```
read_document(md_path, *, collection) -> Document
write_document(md_path, *, frontmatter, body, assets=None) -> Document
move_document(document, *, target_md_path, updates=None) -> Document
remove_document(document) -> None
```

`Document` is frozen: `id`, `collection`, `md_path`, `wrapper_dir`,
`frontmatter` (the validated model), `body`.

Reading validates. That is where "an unrecognised `owner` is refused, naming
the document" actually happens: `read_document` catches pydantic's
`ValidationError` and re-raises `DocumentInvalid` carrying the path, so the
engine's caller sees a domain exception rather than a library one. A document
with no `id` is the same kind of failure.

Writing goes through `replace_file`, so an interrupt leaves the old document
or the new one. A wrapped document writes `content.md` plus its assets inside
the wrapper directory; each asset is its own atomic replace, because the plan
puts documents in the resumable category rather than the all-or-nothing one.

Moving keeps the identifier, and refuses a move that would change it.

### `engine/corpus/collection.py`

```
Collection(root, name)
  .documents()                 -> list[Document], walked and validated
  .resolve(identifier)         -> Document
  .aliases()                   -> dict[str, str]
```

`resolve` tries the literal identifier first, so a real identifier is never
shadowed by an alias. On a miss it consults the alias map, which maps title,
citekey, arXiv identifier, DOI and `project/page` - each also lowercased - to
an identifier, **dropping any key that two documents share**. That is the
plan's "an ambiguous alias resolves to nothing rather than to a guess": the
key is absent from the map, so the lookup misses and `resolve` raises
`DocumentNotFound`, the same as a key nobody ever used.

boepie builds this map from chunk metadata in a loaded index. There is no
index yet, so this one is built from the collection walk. Same algorithm, one
pass, consulted only after the literal lookup misses.

### New domain exceptions

`DocumentNotFound`, `DocumentInvalid` and `UnknownCollection` in
`engine/errors.py`, each with a `default_resolution` naming the command that
helps: `kennis corpus list`, `kennis corpus status`.

### The tests, in the plan's own order

Every one of the plan's eight, as behaviour:

1. a document written and read back is unchanged, frontmatter included;
2. the same arXiv identifier gives the same surrogate identifier, across two
   independent derivations;
3. editing the body does not change the identifier;
4. retitling does not change the identifier;
5. a document is reachable by citekey, arXiv identifier and DOI;
6. an ambiguous alias resolves to nothing;
7. an unrecognised `owner` is refused, naming the document;
8. an interrupted write leaves either the old document or the new one.

Number 8 is the one that needs a mechanism: `os.replace` is monkeypatched to
raise, and the assertion is that the old bytes are still there and no
temporary file is left beside them.

## What I expect to be uncertain or difficult

- **Where the store root comes from.** Settings are milestone 3's problem at
  the earliest, and every path function needs a root now. Threading it as an
  argument is the obvious answer and makes the tests trivial, but it means a
  later settings layer has to be plumbed through rather than consulted, and I
  may find I have chosen the awkward half of that trade.
- **Whether `id_from` is one field or a pair.** Recording `arxiv:1101.1764` in
  one string conflates the kind and the value, and the alternative is two
  fields. One string is what the design's own prose writes, and it round-trips
  through `derive_id` unchanged, so I expect one - but a reader wanting to
  filter on the kind will have to split it.
- **The digest-to-alphabet encoding.** Base 36 over a 128-bit digest, taking
  ten digits, gives about 51 bits. That is fine against collision for any
  realistic corpus, but I have not checked whether `derive_id` and `mint_id`
  can collide with each other, and a derived identifier landing on a note's
  random one would be a genuine bug rather than a curiosity.
- **pydantic `extra="forbid"` against a document kennis itself wrote.** If
  `model_dump(exclude_none=True)` and the model disagree anywhere - a field
  with a default that dumps and then fails to re-validate - the round-trip
  test is where it shows, and I would rather find it there than at milestone 2
  with an ingestion path on top of it.
- **`filterwarnings = ["error"]` meeting pydantic.** pydantic emits warnings
  for shadowed attribute names, which is why the design chose `schema_version`
  over `schema`. If any field name here trips one, the test suite fails rather
  than warns, which is the behaviour I asked for but will still be a surprise
  the first time.

## What actually happened that I did not expect

**The tests were run red this time, and the red was worth having.** Collection
failed with `ModuleNotFoundError` before a line of the implementation existed,
which is the state the previous session skipped. It caught nothing by itself,
but the one genuine failure afterwards was a test bug rather than a code bug,
and I would not have trusted that reading without having watched the suite go
from red to green in one step.

**That failure was the interesting result.** `test_an_unambiguous_alias_survives_
its_neighbour_being_ambiguous` writes two documents with the same title, and
the helper named each file `{title}.md` - so the second write hit
`_refuse_overwriting_another_document` and raised rather than producing the
two-document collection the test was about. The refusal was right; the helper
was wrong. Fixing it meant giving the helper `unique_filename(title_filename(
title), taken)`, which is what the add path will do in milestone 2, so a test
fixture turned out to be a first sketch of production code. Worth noticing:
the same-title case is not exotic, and nothing above `document.py` had yet
been made responsible for allocating a free filename.

**Four of the five predicted difficulties did not appear, again.**
`extra="forbid"` round-tripped cleanly on the first try, including
`source.from` through the alias and the timestamp through `mode="json"`.
pydantic emitted no warnings for any field name, so `filterwarnings =
["error"]` never fired. The `id_from`-as-one-string question answered itself:
`derive_id(id_from)` round-trips, which is the property that makes the field
worth having, and splitting the kind out would break it.

The store root is the one I still think is unresolved rather than answered.
Threading it as an argument made every test trivial and reads well, but
`Collection(root=..., name=...)` now has two constructor arguments where a
caller almost always wants "the machine's corpus", and settings will have to
be plumbed rather than consulted. I have left it, because the alternative -
a module-level root that tests monkeypatch - is the shape that makes a test
suite quietly depend on global state.

**The collision question I named had a better answer than I expected.**
`derive_id` and `mint_id` produce the same shape, so nothing downstream can
tell them apart - which is what makes a collision between them a real bug
rather than a curiosity. The fix is not in the derivation: `mint_id(taken)`
simply has to be called with *every* identifier in the collection, derived
ones included. That is now what its docstring says, and the note is worth
more than a guard would have been, because the caller is the only party that
knows what is taken.

**Two things the plan did not name and the code needed.**

- `engine/frontmatter.py`, the YAML codec. boepie keeps it in `context/`, and
  the corpus imports it from there. In kennis that direction would be wrong -
  the corpus exists before the context bundle - so the codec sits beside
  `_atomic.py` at the engine root, where both will reach it.
- `schema.collection_of(frontmatter)`. `write_document` has to know which
  collection it is writing, and taking it as a separate argument would let the
  model and the directory disagree. The model is the authority, so the writer
  asks it. First attempt reached into `schema._MODELS` from `document.py`,
  which is the same coupling wearing an underscore; the accessor is public
  now.

**`title_filename` and `unique_filename` are ported behaviour the plan does
not list a test for**, and both encode a real failure boepie found - a
dotfile-derived title writing successfully and then being invisible to every
walk, and a document titled "content" turning its own parent into a wrapped
document. Untested ported code is the worst of both, so `tests/test_layout.py`
exists although the plan does not ask for it.

**The plan asks for "two independent runs", and I nearly wrote two calls.**
`derive_id(key) == derive_id(key)` inside one process would pass even if the
derivation depended on a per-process randomised hash seed, which is exactly
the failure that would give two machines different bytes for the same paper.
The test now runs `derive_id` in two subprocesses and compares both against
the in-process result.
