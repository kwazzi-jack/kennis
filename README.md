# kennis

A local knowledge and memory management system for people and AI agents.

kennis holds a corpus of documents, a per-workspace context bundle, and a
retrieval stack over both that combines BM25 with dense embeddings. It is
domain-agnostic: it knows nothing about any particular subject, and domain
content is supplied from outside as data rather than code.

## Status

Pre-release. Everything v0.1 is meant to cover is built and tested - the
corpus with git-backed history, BM25 and dense retrieval over it, and the
command line - but nothing has been published yet, and the on-disk format may
still change without a migration.

An MCP server, a per-workspace context bundle, and the pack format for
supplying domain content come after that.

## Getting started

```
kennis corpus init                      # the corpus, and the git repository it is
kennis corpus add -n notes.md           # -n notes, -l literature, -d docs
kennis corpus index                     # build the search index
kennis search "what you are looking for"
kennis read <document-id>               # the passage around a hit, in full
kennis remember "something worth keeping"
```

`kennis config init` is a guided setup that asks which embedding backend to
use, including none: with no backend the index is lexical only, and search
falls back to BM25 rather than failing.

`kennis remember` writes a note and indexes it in the same command, so what
you have just told kennis is searchable straight away. Every command that
changes the corpus records a commit, and `kennis corpus history` reads them
back.

Documents are converted to markdown on the way in. PDFs need a converter:
`uv sync --extra mineru` installs MinerU, which runs locally and costs
nothing.

## Requirements

- Python 3.12 or newer
- `uv`
- `git`

## Licence

GPL-3.0-or-later. See `LICENSE`.
