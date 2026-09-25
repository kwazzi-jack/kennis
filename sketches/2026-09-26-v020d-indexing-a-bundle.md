# Indexing a bundle

Milestone / step: v0.2.0 unit 3
Date: 2026-09-26

## What I am about to do

`kennis context index`: the existing retrieval engine pointed at a
`.context/` bundle, producing a BM25-only index committed with the project,
so that a fresh clone has working search with no setup.

## How I expect it to work

### The seam already exists and is named

`rag/loaders.py` says it in its own module docstring: "This is the only part
of the retrieval stack that knows what a corpus looks like ... which is what
will let the context bundle use the same engine without a second
implementation." The `Loader` protocol is two members, `name` and
`documents(events=...)`. So unit 3 is one new class, `BundleLoader`, and no
change to chunking, BM25, the index writer or search.

    BundleLoader(bundle).name == "context"
    BundleLoader(bundle).documents() -> list[rag.Document]

`bundle_documents` already decides what counts: every `*.md` at any depth,
less anything dot-prefixed and less `LANDING.md`.

### A document's identity is its path

The corpus mints a surrogate identifier and records it in frontmatter. A
bundle has none and should not gain one: the plan says a context hit's
handle **is** its file path, "the bundle is files in the user's project, not
documents kennis owns". So `Document.id` is the bundle-relative posix path,
which is also `source_path`. Two consequences worth naming:

- the manifest's `documents: {id: digest}` map is keyed by path, so renaming
  a file reads as a delete plus an add, which is what it is on disk;
- nothing needs `base_path` - there are no wrapped documents in a bundle -
  so it stays `None`.

### Where the index goes, and one ugly level I am accepting

`build_index(loader, index_root=...)` writes to `index_root / loader.name`.
With `index_root = .context/.index` and the name `context`, the published
index lands at

    .context/.index/context/<index_id>/

The plan writes `.context/.index/binding.json`, one level shallower. The
plan is describing intent rather than specifying depth - design section 19
says only "`.context/.index/` with its own `binding.json`" - and the extra
level buys something concrete: `load_index(index_root, "context")`,
`read_manifest(index_root, "context")` and the freshness check all work
unchanged. Flattening it would mean parameterising `collection_root` through
three functions the corpus also uses, to remove one hidden directory. Taking
the level.

### The binding is lexical-only, and hardcoded for one more unit

`Binding(chunking=<settings>, model=None)`. `retrieval.context_method` is
unit 7 and the plan orders it after this, so this unit writes `model=None`
with a comment naming the unit that makes it a setting. `_vectors_for`
returns `(None, 0)` for a model-less binding, and `VectorCache` only creates
its directory inside `put`, so a lexical build leaves no cache directory in
the user's repository at all. Checked, not assumed.

### No repository, and therefore no commit-based freshness

`build_index` takes `repository` and records `repository.head()` as
`built_from`. kennis does not own this repository (unit 2's rule), so it
passes `None`, the manifest records no commit, and freshness cannot be a
commit diff.

It does not need to be. The manifest already records `documents: {id:
digest}`, and the digest is of the document text exactly as it is. So "is
this index in step" is: the set of paths matches, and each digest matches.
That is O(bundle) rather than O(changed files), and a bundle is tens of
files. `context status` (unit 5) reads it; this unit only has to make sure
the manifest is written such that it can.

### `.gitignore`, which unit 1 deliberately did not write

There was nothing to ignore before this unit, because `.index/` did not
exist. Now it does, and `corpus.track_index` governs whether it is
committed - design section 19 is explicit that committing it is the point
and that the setting governs it. So:

- `track_index` true (the default): no `.gitignore` line, the index is
  committed with the project.
- `track_index` false: `.context/.gitignore` holds `.index/`.

Written by `context index` rather than by `init`, because the setting can
change between the two and the file that states the answer should be written
by the command that knows it.

### An empty bundle

`_refuse_if_empty` raises `NothingToIndex` naming the collection. A freshly
scaffolded bundle holds only `LANDING.md` and `.skeleton.md`, both excluded,
so this is the *first* thing a new user hits. The message must name
`kennis remember --context` as the resolution, which rule 4.4 allows only
if it runs as printed - so the resolution is the command with no argument,
which reads from standard input, or the message names the help. Deciding
when I see it.

### Frontmatter that is absent is not frontmatter that is broken

`CollectionLoader` reports an unreadable document rather than skipping it,
and milestone 2 spent two commits establishing that. The bundle case is
different in one way: a file a user hand-wrote with no frontmatter block at
all is **not** an error. `split_frontmatter` returns `({}, text)` for it, the
body is the whole file, and it indexes fine. Only a `---` block that parses
to something other than a mapping loses metadata, and that is the diagnostic.

Metadata carried into the index: `title`, `description`, `owner`, and
`group` (the relative directory, `""` at the root), matching what
`CollectionLoader` records so a filter written against one works against the
other.

## What I expect to be uncertain or difficult

Whether `context index` should take a lock. #236 says a bundle has none and
that an index build is not one atomic write, so this is the unit that has to
answer it. `replacing_directory` stages and swaps, and the pointer is
written after the swap, so a concurrent build is a wasted build rather than
a corrupt index. I expect that to be enough and the answer to be "no lock,
and #236 stays open against the write path rather than the build".

Whether the chunk parameters come from the user's corpus settings at all. A
bundle is per-project and the settings are machine-global, so two machines
with different `chunking.size` produce different indexes for the same
committed bundle - and the committed index is the point. The binding file is
what catches it, and the answer is "rebuild, it costs 40ms", but I want to
see whether the rebuild is silent or reported.

Whether an index committed by one machine and read by another actually round
trips. The plan asks for that test explicitly and it is the only one here
that cannot be satisfied by looking at the code: it needs a build, a copy to
a different absolute path, and a search that works with no rebuild.

## What actually happened that I did not expect

**The seam held exactly as advertised.** `BundleLoader` is 60 lines, and
nothing in chunking, BM25, the index writer or search changed. The loader
module's claim - that it is "the only part of the retrieval stack that knows
what a corpus looks like" - turned out to be literally true, which is rare
enough for a claim written a milestone before it was tested.

**Unit 2 had a defect that only unit 3's sketch could see.** Writing "a
header that will not parse costs its metadata and not the file" made me
check what `split_frontmatter` does with invalid YAML, and it raises. Unit
2's dedup scan calls it on every file in the bundle, so one hand-broken
header anywhere would have taken down every later `remember --context`. The
bundles unit 2 was tested against were all written by kennis, so every
header in them parsed. Logged and fixed as #239. The general lesson is the
one the project keeps relearning: a fixture built by the code under test
cannot exercise what a human being does to a file.

**Two tests passed with their defect injected, and both were mine.** The
emptiness refusal at the command line asserted only a non-zero exit, which
`build_index`'s own `_refuse_if_empty` guarantees whatever the bundle
wording does - so it would have passed with the entire translation removed.
And nothing at all tested that the command reads the configured chunk size;
`chunking=None` passed the whole file. Both are now asserted on the thing
that actually distinguishes the behaviour: the message a reader gets, and
the value recorded in `binding.json`.

**Removing a redundant guard was the right fix, not adding a test for it.**
The emptiness check I wrote first called `loader.documents()` and then let
`build_index` read every file again to reach the same conclusion. Replacing
it with a `try/except NothingToIndex` around the build removed the double
read and made the wording the only thing the wrapper contributes - which is
also what made the injection bite, because there is now exactly one place
the behaviour lives.

**A dead assignment hid an injection.** The frontmatter fallback set
`frontmatter, body = {}, text` in its `except` clause and the diagnostic
path then ended in `return {}, text`, so corrupting the except clause
changed nothing observable. The second copy of the answer was silently
covering for the first. Changed to return the values the split produced, and
the injection fails as it should. This is the same shape as #63 - a property
tested somewhere it could not fail - arriving through duplication rather
than through ordering.

**The clone test was weaker than it looked.** Copying a bundle to a new path
and searching it passes even if every path in the index is absolute, because
the original is still there. Deleting the original after the copy is what
makes it a test, and it now also asserts the hit's `source_path` is
relative.

**Measurements, since the design quotes boepie's.** Three documents, three
chunks, 4ms, and 2.8 KB of published index across nine files - `chunks.jsonl`
is 1.2 KB of it, which is the bundle's own text a second time. Design section
19 quotes 122 chunks in 40ms for boepie's real bundle; this is consistent
with it. Small enough that `corpus.track_index` is a preference rather than a
necessity, which is why #240 records the missing setting instead of inventing
it.

**The uncertainties resolved as expected, and one did not come up.** No
lock: `build_index` stages into a temporary directory and writes the pointer
after the swap, so a concurrent build wastes itself rather than corrupting
anything, and #236 stays open against the write path. The chunk parameters do
come from the machine-global settings, which is visible in `binding.json` and
is what a second machine compares - `chunk_parameters` was factored out of
`binding_from` so the bundle and the corpus cannot derive them differently.
Whether a rebuild is silent or reported never arose, because unit 3 only
builds; it is unit 5's question.

**One rule-4.4 violation found in existing code.** `load_index` names
`kennis corpus index --collection <name>` when an index is missing, and
`context` is not one of the three values that option accepts. Contained by
`load_bundle_index`, logged as #241.
