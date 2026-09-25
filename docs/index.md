# kennis

A knowledge and memory system for people and AI agents: a document corpus you
own, and retrieval over it that searches by meaning as well as by words.

kennis is **domain-agnostic**. It knows nothing about any particular subject.

```
kennis corpus add paper.pdf --literature
kennis corpus index
kennis search "why does rank fusion beat score fusion"
kennis read yusk5agyfk --chunks 2:5
```

## What it is

A corpus of markdown documents in three collections - `literature`, `docs`
and `notes` - stored as ordinary files in ordinary directories, in a git
repository, that you can read and edit without kennis being involved.

Over that, two retrieval legs fused into one ranking: BM25 for the words you
typed, and dense embeddings for what you meant. See
[How retrieval works](explanation/retrieval.md).

## What makes it different

**Your documents stay yours.** Conversion runs locally by default and
embedding runs locally by default. Sending a document to a third party
requires setting a backend *and* supplying a key - never one without the
other, and never as a default.

**The relevance level is measured, not invented.** When kennis says a hit is
`high`, that is a cosine similarity against cuts measured on a real corpus
for that specific model. When it cannot make an absolute claim it says so in
the summary line, and when it has no scale at all it shows no level rather
than inventing one.

**A handle never breaks.** A document's identifier is surrogate and fixed at
creation, so you can retitle, regroup, or move a document between collections
and everything that referenced it still resolves.

**The output is a payload.** `kennis read x > x.md` gives you the document
byte for byte. Colour is dropped when stdout is not a terminal, and no line
is padded or re-wrapped.

## Where to start

<div class="grid cards" markdown>

- **New here?**
  [Install](getting-started/install.md), then the
  [tutorial](getting-started/tutorial.md) - fifteen minutes, no PDFs, no keys.

- **Want to do one thing?**
  The [how-to guides](how-to/add-documents.md) are task-shaped.

- **Want to know why?**
  [How retrieval works](explanation/retrieval.md) is the one to read.

- **Looking up an option?**
  [Commands](reference/cli.md), generated from the code.

</div>

## Status

Version 0.1.1. The corpus, search and the command line are built. Packs, the
per-workspace context bundle, and the MCP server are not - they are planned
for 0.2.0 and later.

This is experimental software under active development. It keeps no
backwards-compatibility shims: when something is reworked, the old path is
removed rather than deprecated.
