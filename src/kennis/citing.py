"""Citing passages: what `kennis cite` and the MCP tool `cite` answer (#572).

For each passage asked for - a document by any handle `kennis read` takes,
and a chunk of it or none - a citation in the configured style with the
chunk's locator, its entry in a list of references, and its `kennis://`
link. The agent composes none of these (#572), so a citation cannot name a
paper kennis does not hold or a place the link does not open.

Beside `finding.py`, because the service answers it for every client and it
resolves a handle as that module does.

**One request's failure is its own.** A batch from an agent names several
hits, and one removed document must not cost the others, as for the
`read_*` tools; a failure is a `CiteRefusal` at its position.

**Alike is said, not fixed** (#593). Two passages whose citations read the
same and whose links differ - two chunks of a note, which has no locator -
are each told the other's position, so a reader is not left thinking two
links are one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from kennis.context import Context
from kennis.engine.citing.locators import Locator, locator_of
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import KennisError, SearchUnavailable
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.models import Chunk
from kennis.finding import resolve_document
from kennis.links import link_to
from kennis.publishing import reading
from kennis.render.citations import ToCite, formatted, style_path


@dataclass(frozen=True, slots=True)
class CiteRequest:
    """A passage to cite: a document by any handle, and its chunk if any."""

    handle: str
    chunk: int | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """One passage, cited."""

    position: int
    document_id: str
    collection: str
    chunk: int | None
    citation: str
    reference: str
    locator: Locator | None
    link: str
    # The positions of the other citations that read the same and open
    # somewhere else.
    alike: list[int] = field(default_factory=list)

    @property
    def markdown(self) -> str:
        """The citation as a link, to write where markdown is shown."""
        return f"[{self.citation}]({self.link})"


@dataclass(frozen=True, slots=True)
class CiteRefusal:
    """A request that could not be cited, and why."""

    position: int
    handle: str
    message: str
    resolution: str | None


@dataclass(frozen=True, slots=True)
class Cited:
    """A batch's citations, in the order asked, and its refusals."""

    citations: list[Citation]
    refused: list[CiteRefusal]


@dataclass(frozen=True, slots=True)
class _Found:
    position: int
    collection: str
    chunk: int | None
    passage: ToCite
    document_id: str


@reading
def cite(context: Context, requests: Sequence[CiteRequest]) -> Cited:
    """Every request cited, or refused at its own position."""
    found: list[_Found] = []
    refused: list[CiteRefusal] = []
    indexes: dict[str, LoadedIndex] = {}
    for position, request in enumerate(requests):
        try:
            found.append(_found(context, position, request, indexes))
        except KennisError as error:
            refused.append(
                CiteRefusal(
                    position=position,
                    handle=request.handle,
                    message=str(error),
                    resolution=error.resolution,
                )
            )
    style = style_path(context.settings.literature.citation_style)
    written = formatted([each.passage for each in found], style)
    citations = [
        Citation(
            position=each.position,
            document_id=each.document_id,
            collection=each.collection,
            chunk=each.chunk,
            citation=text.citation,
            reference=text.reference,
            locator=each.passage.locator,
            link=link_to(each.document_id, each.chunk),
        )
        for each, text in zip(found, written, strict=True)
    ]
    return Cited(citations=_marked_alike(citations), refused=refused)


def _found(
    context: Context,
    position: int,
    request: CiteRequest,
    indexes: dict[str, LoadedIndex],
) -> _Found:
    where, document = resolve_document(context, request.handle, None)
    locator: Locator | None = None
    if request.chunk is not None:
        if where.name not in indexes:
            indexes[where.name] = load_index(
                index_root(context.corpus_root), where.name
            )
        chunk = _chunk_of(indexes[where.name], document.id, request.chunk)
        locator = locator_of(document.body, chunk.char_start, chunk.char_end)
    return _Found(
        position=position,
        collection=where.name,
        chunk=request.chunk,
        passage=ToCite(frontmatter=document.frontmatter, locator=locator),
        document_id=document.id,
    )


def _chunk_of(index: LoadedIndex, document_id: str, number: int) -> Chunk:
    for chunk in index.chunks:
        if chunk.document_id == document_id and chunk.chunk_index == number:
            return chunk
    raise SearchUnavailable(
        f"'{document_id}' has no chunk {number} in the '{index.collection}' index",
        resolution="kennis corpus index",
    )


def _marked_alike(citations: list[Citation]) -> list[Citation]:
    """Each citation with the positions of those that read the same and
    open somewhere else."""
    return [
        replace(
            citation,
            alike=[
                other.position
                for other in citations
                if other.citation == citation.citation and other.link != citation.link
            ],
        )
        for citation in citations
    ]


__all__ = ["Citation", "CiteRefusal", "CiteRequest", "Cited", "cite"]
