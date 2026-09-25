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

Pre-release. Everything v0.1 is meant to cover is built and tested - the
corpus with git-backed history, BM25 and dense retrieval over it, and the
command line - but nothing has been published yet, and the on-disk format may
still change without a migration.

An MCP server, a per-workspace context bundle, and the pack format for
supplying domain content come after that.

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
```

A hit looks like this:

```
Found 2 passages, relevance by cosine similarity
  [1] [literature] Calibration of radio interferometers - Gain solutions
      relevance: very high  id=gpfa1o3yad chunk=3
      Complex gains are solved per antenna and per interval ...
```

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
