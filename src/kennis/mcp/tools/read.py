"""The `read` tool: the follow-up to a search hit.

A search answers "where", with a `document_id` and a `chunk`; these
answer "what it actually says". The two halves are deliberately separate
so that ten hits cost ten snippets and only the one worth expanding
costs a passage.

**A context hit is not read here.** A bundle file lives in the user's
own repository, so `search` returns its path and the agent opens it with
its native file tools - the same reason `kennis read` refuses
`--collection context`.

**One tool, and the document says which collection it is in** (#643).
It was three, the collection fixed by which was called, so that a note
could not be served as a paper. A `document_id` is found across the
collections, as `kennis read` finds it without `--collection`, and the
provenance line that opens each answer names the collection it was
found in.

**The provenance line is not composed here.** `render/words.py` already
phrases both kinds - `describe_document` for a whole document and
`describe_span` for a range - and the command line prints the same two,
so a person running `kennis read` sees the line the model saw. Design
section 20's exception covers spans as it covers hits.

**Requests are batched.** An agent following up three hits from one
search should not pay three round trips, and a batch is also where the
failure rule lives: one bad identifier is reported in its own block and
the other requests are still answered. A call that raised would make
the agent's error recovery "guess which of the three was wrong".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.context.bundle import BUNDLE_DIRNAME
from kennis.engine.corpus.document import Document
from kennis.engine.errors import KennisError
from kennis.engine.rag.search import ChunkRange
from kennis.render.words import describe_document, describe_span

# How much of a whole document one answer carries. A tool's answer goes
# into a context window, and a converted paper runs to hundreds of
# kilobytes: read whole it would crowd out the conversation that asked
# for it. The cut is announced rather than silent, because an agent
# handed a truncated document with no sign of it would go on to reason
# about a text it has only the first part of.
_MAX_CHARACTERS: Final = 20_000

# How many requests one call may carry. Enough for every hit of a
# default search, few enough that the answer stays readable.
_MAX_REQUESTS: Final = 8

_NOTHING: Final = "no requests"


@dataclass(frozen=True)
class ReadRequest:
    """One document to read, and how much of it.

    `chunk_index` is a hit's `chunk`, copied from a search answer.
    Omitted, the whole document is read - which needs no index, so a
    document added but never indexed is still readable.

    `before` and `after` widen the window around `chunk_index`, in
    chunks. The defaults give the hit with one chunk either side, which
    is usually enough to recover a sentence cut at a chunk boundary.
    """

    document_id: str
    chunk_index: int | None = None
    before: int = 1
    after: int = 1


def read(requests: list[ReadRequest]) -> str:
    """Read passages of documents in `notes`, `literature` or `docs`.

    Call this on a `document_id` from `search` or `list_corpus`. Pass the
    hit's `chunk` as `chunk_index` to expand that passage, with `before`
    and `after` widening it by whole chunks; omit `chunk_index` to read
    the whole document. Expanding a hit before citing it is the point: a
    snippet is enough to rank a document and not enough to quote it.

    Each answer opens with a line naming the document and the collection
    it is in. Several requests are answered in one call, and one that
    fails does not cost the others.

    Not for a `context` hit: that is a file in the user's repository,
    which you open with your native file tools.
    """
    if not requests:
        return _NOTHING
    if len(requests) > _MAX_REQUESTS:
        return (
            f"{len(requests)} requests is more than one call reads. "
            f"Ask for at most {_MAX_REQUESTS}, best first."
        )
    corpus_root = existing_corpus().corpus_root
    return "\n\n".join(_answered(corpus_root, request) for request in requests)


def _answered(corpus_root: Path, request: ReadRequest) -> str:
    """One request: its provenance line, then its text.

    Every domain failure becomes a block rather than an exception. The
    note a `KennisError` carries names the command that resolves it, so
    an agent reading a failed block is told what a person would be. A
    whole document needs no index, so a batch of them answers on a corpus
    never indexed; each request is its own call to the service.
    """
    if request.document_id.startswith(f"{BUNDLE_DIRNAME}/"):
        # A context hit's handle, which `search` prints as `path=`.
        return (
            f"{request.document_id}: this is a file in the project's own "
            "repository, not a document kennis holds. Open it with your file tools."
        )
    if request.chunk_index is not None and request.chunk_index < 0:
        return (
            f"{request.document_id}: chunk_index {request.chunk_index} is negative. "
            "Pass the `chunk` of a search hit, which counts from 0."
        )
    try:
        if request.chunk_index is None:
            # No collection: the identifier is found across them, and the
            # answer's first line says where.
            read = api.read_document(
                corpus_root, request.document_id, None, frontmatter=False
            )
            return _whole(read.collection, read.document, read.text, corpus_root)
        return _range(corpus_root, request)
    except KennisError as error:
        return _failed(request.document_id, error)


def _whole(collection: str, document: Document, body: str, corpus_root: Path) -> str:
    """A document read in full, cut if it is long.

    The cut names `chunk_index` rather than a byte offset, because that
    is the argument that reads the rest and there is no other.
    """
    body = body.strip("\n")
    if len(body) > _MAX_CHARACTERS:
        body = (
            f"{body[:_MAX_CHARACTERS]}\n\n"
            f"... cut after {_MAX_CHARACTERS} of {len(document.body)} characters. "
            "Read the rest a part at a time with `chunk_index`."
        )
    provenance = describe_document(collection, document, corpus_root)
    return f"{provenance}\n{body}"


def _range(corpus_root: Path, request: ReadRequest) -> str:
    """A window of chunks around the one a hit named.

    `max(0, ...)` on the start is not defensive tidiness: `ChunkRange`
    resolves like a python slice, so `chunk_index=0` with `before=1`
    would compute `-1` and read the document's *last* chunk - the wrong
    end of it, silently, for the most common hit there is.
    """
    assert request.chunk_index is not None
    chunks = ChunkRange(
        start=max(0, request.chunk_index - max(0, request.before)),
        stop=request.chunk_index + max(0, request.after) + 1,
    )
    read = api.read_passage(corpus_root, request.document_id, None, chunks=chunks)
    provenance = describe_span(read.collection, read.span, read.title)
    return f"{provenance}\n{read.span.text.strip()}"


def _failed(document_id: str, error: KennisError) -> str:
    """One request that could not be served, named so the rest are usable."""
    resolution = f" Run `{error.resolution}`." if error.resolution else ""
    return f"{document_id}: {error}.{resolution}"


__all__ = ["ReadRequest", "read"]
