# kennis

A local knowledge and memory management system for people and AI agents.

kennis holds a corpus of documents, a per-workspace context bundle, and a
retrieval stack over both that combines BM25 with dense embeddings. It is
domain-agnostic: it knows nothing about any particular subject, and domain
content is supplied from outside as data rather than code.

## Documentation

Full documentation - a tutorial, how-to guides, the reasoning behind each
mechanism, and a command reference generated from the code - is built with
MkDocs:

```
uv run --group docs mkdocs serve      # http://127.0.0.1:8000
uv run --group docs mkdocs build      # into site/
```

## Status

Pre-release, and nothing has been published. Two scopes of knowledge are
built and tested:

- **the corpus**, machine-global, with git-backed history, BM25 and dense
  retrieval over it, and the command line (v0.1);
- **the context bundle**, one per project, committed with it, with its own
  lexical index and searched alongside the corpus (v0.2).

An MCP server and the pack format for supplying domain content come after
that.

**The on-disk format may still change without a migration.** Every
frontmatter model refuses an unknown key rather than ignoring it, so a corpus
written by a later version is not readable by an earlier one, and there is no
version recorded on a document to say so. That is a deliberate choice about
failing loudly, and it is why a corpus built now is a corpus you should be
prepared to rebuild.

## Install

Not published yet, so from source:

```
git clone git@github.com:kwazzi-jack/kennis.git
cd kennis
uv sync                       # add --extra mineru to convert PDFs
uv run kennis --help
```

To get a `kennis` on your PATH instead of prefixing every command with
`uv run`, install it as a tool. Converting PDFs needs the `mineru` extra,
which is a large download:

```
uv tool install .                       # or
uv tool install "kennis[mineru] @ ."    # with PDF conversion
```

`uv tool install` links only the requested package's executables, so `mineru`
itself does not land on your PATH - kennis finds it in the environment it was
installed into.

## Usage

### Set up

```
kennis config init            # guided: embedding, conversion, retrieval, paths
kennis config show            # valid TOML, safe to redirect to a file
kennis config get embedding.backend
kennis config set embedding.backend none
```

Nothing here is required. With no configuration kennis uses its defaults and
`KENNIS_EMBEDDING_BACKEND=none` gives a lexical-only index, which needs no
model download and is the quickest way to try it.

### Put something in

```
kennis corpus init                             # the corpus, and the git repository it is
kennis corpus add -n notes.md --group radio    # a file, or a directory, into notes
kennis corpus add -l arXiv:2101.11270          # a paper, by identifier or DOI
kennis corpus add -d https://docs.astropy.org/en/stable/ --max-pages 20
```

Three collections, each with a shorthand: `-n` notes, `-l` literature, `-d`
docs. They differ in what kennis does *besides* storing the markdown -
literature resolves bibliographic identity and derives a citekey, docs
records which project and page a document is.

Adding a site is polite by default: it waits between requests, honours
`robots.txt`, and stops at `--max-pages`. Twenty pages takes about a minute.

### Search it

```
kennis corpus index                            # build the index; after any batch of adds
kennis search "complex gains"
kennis search "gains" --collection notes --group radio -k 5
kennis search "fits files" --mode bm25 --snippet full
kennis search "complex gains" --scores raw     # the per-leg numbers instead of a level
kennis search "gains" --collection context     # this project's bundle only
kennis search "gains" --collection notes,context
```

`--collection` takes a comma-separated list over four scopes - `literature`,
`docs`, `notes` and `context` - and defaults to `all`. A scope you name is a
promise and a scope you did not is not: asking for `context` outside a
project is an error, while a sweep outside one simply does not mention it.

A hit looks like this:

```
Found 2 in literature, 1 in notes

Literature relevance by cosine similarity
  [1] Calibration of radio interferometers - Gain solutions
      relevance: very high  id=gpfa1o3yad chunk=3
      Complex gains are solved per antenna and per interval ...

Notes relevance relative to the best lexical match
  [1] Calibration conventions
      relevance: very high  id=f4inoeh3gd chunk=0
      We solve gains on a 30 second interval ...
```

**Results are grouped by collection, and that is not only cosmetic.** Each
group carries the scale its own levels are on. A collection indexed without
an embedding backend is banded relative to its own best hit, where one with
a dense leg is banded on an absolute cosine - and those two `very high`
above mean different things. Ordering them into one column would state a
comparison kennis cannot make. `-k` applies per group.

`id` and `chunk` are what `read` takes. `--mode` is `hybrid` by default and
falls back to `bm25` against a lexical-only index rather than failing.

The first index on a new machine downloads the embedding model, which kennis
says it is doing and keeps in `~/.cache/kennis/models`, so it is paid once.
With `embedding.backend = ollama`, a model the daemon does not hold is pulled
the same way.

**Relevance is measured, not invented.** With a dense leg and an embedding
model kennis has calibrated, the level is the hit's cosine similarity against
cuts measured on a real corpus, so it means the same thing for every query.
Against a lexical-only index it is relative to the best hit of that query,
and the summary line says which of the two you are reading. `--scores raw`
gives the numbers themselves.

Reading a document:

```
kennis read 3vgtsow3cl                         # the whole document, as markdown
kennis read "Recipe for-loops.md"              # by filename, title, or citekey
kennis read 3vgtsow3cl --chunks 2:5            # just those chunks
kennis read 3vgtsow3cl > paper.md              # the report goes to stderr, so this works
```

`--chunks` is a python slice over the document's own chunks: `3` is one,
`0:3` is the first three, `2:` runs to the end, `-1` is the last. There is no
step, because a passage that is not contiguous is not a passage. Without it
the document is read from the corpus, so a document that has never been
indexed is still readable; with it the passage is stitched out of the index.

Either way stdout is the text and stderr is the provenance, so both forms
pipe and redirect cleanly. Redirected, the text is the document byte for
byte: colour is dropped when stdout is not a terminal, and no line is padded
or re-wrapped.

**Code blocks are highlighted where the language is known.** A fence that
names one (` ```yaml `) is lexed as that. A fence that names nothing is
*parsed* rather than guessed at - if the text is a YAML or JSON document it
is highlighted as one, and otherwise it is coloured as a single block and
left alone. Guessing was tried and measured: over 262 unlabelled fences it
answered MySQL, GDScript, scdoc and Tera Term macro for content that was
plainly YAML, so it is not used.

### Write something down

```
kennis remember "QuartiCal needs --input-ms-time-chunk tuned for long tracks"
kennis remember --from jottings.md --title "Jottings"
echo "The array has 64 dishes." | kennis remember
```

`remember` writes a note and indexes it in the same command, so what you have
just told kennis is searchable straight away - provided the notes collection
has already been indexed once. It says which of the two happened.

### Knowledge that belongs to one project

```
kennis context init                                  # a .context/ bundle at the workspace root
kennis remember --context "Calibration runs in four-minute chunks"
kennis remember --context --group decisions --title "Solver" "We use quartical"
kennis context index                                 # BM25 only, offline, milliseconds
kennis context status                                # what it holds, and whether the index is in step
```

The corpus is machine-global; a bundle belongs to one project and is
committed with it, so the knowledge travels with a clone. **The index does
not travel** - it is derived, rebuilt in milliseconds, and specific to
whoever built it, so `context init` gitignores it and a clone runs
`kennis context index` once.

kennis never commits to your repository. Committing `.context/` is yours to
do.

### See what is there

```
kennis corpus status                           # per collection: how many, and how stale
kennis corpus list --collection notes
kennis corpus tree
kennis corpus history --limit 10
kennis corpus restore <document-id> --commit <hash>
```

Every command that changes the corpus records a commit, so `history` is the
record of what kennis did and `restore` puts a document back as it was.

### Where things live

| what | where | override |
|---|---|---|
| the corpus | `~/.local/share/kennis` | `KENNIS_CORPUS_ROOT` |
| a project's context bundle | `.context/` at the workspace root | `KENNIS_CONTEXT_DIR` |
| configuration | `~/.config/kennis` | `KENNIS_CONFIG_DIR` |
| the log | `~/.local/state/kennis/log` | `KENNIS_LOG_DIR` |
| downloaded embedding models | `~/.cache/kennis/models` | - |

Every setting can also be given as an environment variable:
`KENNIS_EMBEDDING_BACKEND`, `KENNIS_CONVERSION_BACKEND`, and so on. The log is
always on, and an error tells you where it is.

## Requirements

- Python 3.12 or newer
- `uv`
- `git`

## Licence

GPL-3.0-or-later. See `LICENSE`.
