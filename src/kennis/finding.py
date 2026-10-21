"""Turning a handle a person typed into the document it addresses, and
reading it.

Shared by every command that takes one - `corpus remove`, `corpus move` and
`read` - so that a name working for one works for all of them. Beside
`holdings.py` rather than in `cli/`, because the service answers these for
every client (14c), as it answers what the corpus holds.

The rule itself: without `--collection` all three are tried, and a handle
resolving in more than one is refused. That is the same rule one collection
applies to its own aliases, applied once more at the level above.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from kennis.context import Context
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import DocumentNotFound, SearchUnavailable
from kennis.engine.rag.index import load_index
from kennis.engine.rag.search import ChunkRange, DocumentSpan, read_span
from kennis.publishing import reading


@reading
def resolve_document(
    context: Context, handle: str, collection: str | None
) -> tuple[Collection, Document]:
    """The collection holding `handle`, and the document it addresses.

    Without `--collection` all three are tried, and a handle that resolves in
    more than one is refused. That is the same rule one collection applies to
    its own aliases - a key two documents share addresses nothing - applied
    once more at the level above.
    """
    searched = [collection] if collection else list(COLLECTION_NAMES)
    found: list[tuple[Collection, Document]] = []
    for name in searched:
        candidate = Collection(root=context.corpus_root, name=name)
        try:
            found.append((candidate, candidate.resolve(handle)))
        except DocumentNotFound:
            continue

    if not found:
        raise DocumentNotFound(
            f"no document '{handle}' in {named_collections(searched)}",
            resolution="kennis corpus list",
        )
    if len(found) > 1:
        raise DocumentNotFound(
            f"'{handle}' addresses a document in "
            f"{named_collections([name.name for name, _ in found])}",
            resolution="kennis corpus list",
        )
    return found[0]


def named_collections(collections: Sequence[str]) -> str:
    if len(collections) == 1:
        return f"the {collections[0]} collection"
    return f"{', '.join(collections[:-1])} or {collections[-1]}"


@dataclass(frozen=True, slots=True)
class Found:
    """The collection a handle resolved in, and the document."""

    collection: str
    document: Document


@reading
def found_document(context: Context, handle: str, collection: str | None) -> Found:
    """`resolve_document` as a value that crosses the wire."""
    where, document = resolve_document(context, handle, collection)
    return Found(collection=where.name, document=document)


@dataclass(frozen=True, slots=True)
class DocumentRead:
    """A whole document as read: its body, or with `frontmatter` the file."""

    collection: str
    document: Document
    text: str


@reading
def read_document(
    context: Context, handle: str, collection: str | None, *, frontmatter: bool
) -> DocumentRead:
    """The document `handle` names, **from the corpus**, not from the index,
    so a document never indexed is still readable."""
    where, document = resolve_document(context, handle, collection)
    text = (
        document.md_path.read_text(encoding="utf-8") if frontmatter else document.body
    )
    return DocumentRead(collection=where.name, document=document, text=text)


@dataclass(frozen=True, slots=True)
class PassageRead:
    """One range of a document's chunks, stitched out of the index."""

    collection: str
    title: str
    span: DocumentSpan


@reading
def read_passage(
    context: Context, handle: str, collection: str | None, *, chunks: ChunkRange
) -> PassageRead:
    """The handle is resolved against the corpus first, so a passage accepts
    every name a whole-document read does. Only then is the index asked, and
    only the collection the document was found in, where an index is
    required: `NothingToIndex` names the command that builds it."""
    where, document = resolve_document(context, handle, collection)
    index = load_index(index_root(context.corpus_root), where.name)
    try:
        span = read_span(index, document.id, chunks=chunks)
    except SearchUnavailable as error:
        # In the corpus and not in the index: a stale index rather than a
        # missing document, so the way out is to rebuild.
        error.add_note("run `kennis corpus index`")
        raise
    return PassageRead(
        collection=where.name, title=document.frontmatter.title, span=span
    )


__all__ = [
    "DocumentRead",
    "Found",
    "PassageRead",
    "found_document",
    "named_collections",
    "read_document",
    "read_passage",
    "resolve_document",
]
