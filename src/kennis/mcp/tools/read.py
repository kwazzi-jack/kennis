"""The three `read_*` tools: the follow-up to a search hit.

A search answers "where", with a `document_id` and a `chunk`; these
answer "what it actually says". The two halves are deliberately separate
so that ten hits cost ten snippets and only the one worth expanding
costs a passage.

**There is no `read_context`.** A bundle file lives in the user's own
repository, so `search_context` returns paths and the agent opens them
with its native file tools - the same reason `kennis read` refuses
`--collection context`.

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

from kennis.context import Context, existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import KennisError
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.search import ChunkRange, read_span
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


def read_notes(requests: list[ReadRequest]) -> str:
    """Read passages from notes - the user's own material.

    Call this on a `document_id` from `search_notes` or `list_corpus`.
    Pass the hit's `chunk` as `chunk_index` to expand that passage;
    omit it to read the whole note.

    Several requests are answered in one call, and one that fails does
    not cost the others.
    """
    return _read("notes", requests)


def read_literature(requests: list[ReadRequest]) -> str:
    """Read passages from the literature collection - papers.

    Call this on a `document_id` from `search_literature`. Expanding a
    hit before citing it is the point: a snippet is enough to rank a
    paper and not enough to quote it.

    Several requests are answered in one call.
    """
    return _read("literature", requests)


def read_docs(requests: list[ReadRequest]) -> str:
    """Read passages from the docs collection - documentation sites.

    Call this on a `document_id` from `search_docs` or `list_corpus`,
    with the hit's `chunk` as `chunk_index`. A configuration key or a
    signature usually needs the surrounding paragraph, which is what
    `before` and `after` widen to.

    Several requests are answered in one call.
    """
    return _read("docs", requests)


def _read(collection: str, requests: list[ReadRequest]) -> str:
    """Every request in one collection, each rendered into its own block.

    The collection is fixed by which tool was called rather than passed
    in, so `read_literature` cannot serve a note: an agent citing what
    came back would otherwise attribute a user's jotting to a paper.
    """
    if not requests:
        return _NOTHING
    if len(requests) > _MAX_REQUESTS:
        return (
            f"{len(requests)} requests is more than one call reads. "
            f"Ask for at most {_MAX_REQUESTS}, best first."
        )
    context = existing_corpus()
    held = Collection(root=context.corpus_root, name=collection)
    index = _Lazy(context, collection)
    return "\n\n".join(
        _answered(collection, held, index, request) for request in requests
    )


def _answered(
    collection: str, held: Collection, index: _Lazy, request: ReadRequest
) -> str:
    """One request: its provenance line, then its text.

    Every domain failure becomes a block rather than an exception. The
    note a `KennisError` carries names the command that resolves it, so
    an agent reading a failed block is told what a person would be.
    """
    if request.chunk_index is not None and request.chunk_index < 0:
        return (
            f"{request.document_id}: chunk_index {request.chunk_index} is negative. "
            "Pass the `chunk` of a search hit, which counts from 0."
        )
    try:
        document = held.resolve(request.document_id)
        if request.chunk_index is None:
            # `held.root` is the corpus root, which is the same value
            # the index loader relativises against - so the two kinds
            # of read cannot address the corpus differently.
            return _whole(collection, document, held.root)
        return _range(collection, index.get(), document, request)
    except KennisError as error:
        return _failed(request.document_id, error)


def _whole(collection: str, document: Document, corpus_root: Path) -> str:
    """A document read in full, cut if it is long.

    The cut names `chunk_index` rather than a byte offset, because that
    is the argument that reads the rest and there is no other.
    """
    body = document.body.strip("\n")
    if len(body) > _MAX_CHARACTERS:
        body = (
            f"{body[:_MAX_CHARACTERS]}\n\n"
            f"... cut after {_MAX_CHARACTERS} of {len(document.body)} characters. "
            "Read the rest a part at a time with `chunk_index`."
        )
    provenance = describe_document(collection, document, corpus_root)
    return f"{provenance}\n{body}"


def _range(
    collection: str, index: LoadedIndex, document: Document, request: ReadRequest
) -> str:
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
    span = read_span(index, document.id, chunks=chunks)
    provenance = describe_span(collection, span, document.frontmatter.title)
    return f"{provenance}\n{span.text.strip()}"


def _failed(document_id: str, error: KennisError) -> str:
    """One request that could not be served, named so the rest are usable."""
    resolution = f" Run `{error.resolution}`." if error.resolution else ""
    return f"{document_id}: {error}.{resolution}"


class _Lazy:
    """The collection's index, loaded at most once and only if asked.

    A batch of whole-document reads must not fail on a corpus that has
    never been indexed, and a batch of chunk reads must not load the
    index once per request.
    """

    def __init__(self, context: Context, collection: str) -> None:
        self._context = context
        self._collection = collection
        self._loaded: LoadedIndex | None = None

    def get(self) -> LoadedIndex:
        if self._loaded is None:
            self._loaded = load_index(
                index_root(self._context.corpus_root), self._collection
            )
        return self._loaded


__all__ = ["ReadRequest", "read_docs", "read_literature", "read_notes"]
