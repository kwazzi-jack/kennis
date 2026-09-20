# kennis

A local knowledge and memory management system for people and AI agents.

kennis holds a corpus of documents, a per-workspace context bundle, and a
retrieval stack over both that combines BM25 with dense embeddings. It is
domain-agnostic: it knows nothing about any particular subject, and domain
content is supplied from outside as data rather than code.

## Status

Early development. Nothing is usable yet.

The first release will cover the corpus, search, and a command-line interface.
An MCP server, a per-workspace context bundle, and the pack format for
supplying domain content follow after that.

## Requirements

- Python 3.12 or newer
- `uv`
- `git`

## Licence

Not yet chosen.
