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

**A context passage is cited too** (#623): a file in a project's bundle,
named by `bundle` with its path as the handle, found by membership as the
window finds it, cited as a note is and linked by `kennis://context/...`.
A pack's context is a copy in the bundle (#624), cited the same way. The
client turns
what a hit prints into the bundle (`client/passages.py`), because only it
knows which project it is in.

**Alike is said, not fixed** (#593). Two passages whose citations read the
same and whose links differ - two chunks of a note, which has no locator -
are each told the other's position, so a reader is not left thinking two
links are one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from kennis.context import Context
from kennis.engine.citing.locators import Locator, locator_of
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import KennisError, SearchUnavailable
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import passage_words
from kennis.finding import resolve_document
from kennis.links import Target, context_link, link_to
from kennis.publishing import reading
from kennis.render.citations import (
    Formatted,
    ToCite,
    formatted,
    located_note,
    style_path,
)


@dataclass(frozen=True, slots=True)
class CiteRequest:
    """A passage to cite: a document by any handle, and its chunk if any.

    With `bundle`, `handle` is a path in that project's bundle.
    """

    handle: str
    chunk: int | None = None
    bundle: Path | None = None


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
    # The passage's words as kennis quotes them, for a client that copies
    # them with the citation; None when the whole document is cited.
    passage: str | None = None

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
    document_id: str
    link: str
    # A corpus passage, for the style to write; a context passage comes
    # written, as a note is.
    passage: ToCite | None = None
    written: Formatted | None = None
    locator: Locator | None = None
    words: str | None = None


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
    in_corpus = [each for each in found if each.passage is not None]
    styled = iter(
        formatted(
            [each.passage for each in in_corpus if each.passage is not None],
            style_path(context.settings.literature.citation_style),
        )
        if in_corpus
        else []
    )
    citations: list[Citation] = []
    for each in found:
        text = each.written if each.written is not None else next(styled)
        citations.append(
            Citation(
                position=each.position,
                document_id=each.document_id,
                collection=each.collection,
                chunk=each.chunk,
                citation=text.citation,
                reference=text.reference,
                locator=each.locator,
                link=each.link,
                passage=each.words,
            )
        )
    return Cited(citations=_marked_alike(citations), refused=refused)


def _found(
    context: Context,
    position: int,
    request: CiteRequest,
    indexes: dict[str, LoadedIndex],
) -> _Found:
    if request.bundle is not None:
        return _found_in_bundle(position, request, request.bundle)
    where, document = resolve_document(context, request.handle, None)
    locator: Locator | None = None
    words: str | None = None
    if request.chunk is not None:
        if where.name not in indexes:
            indexes[where.name] = load_index(
                index_root(context.corpus_root), where.name
            )
        chunk = _chunk_of(indexes[where.name], document.id, request.chunk)
        locator = locator_of(document.body, chunk.char_start, chunk.char_end)
        words = passage_words(chunk.text)
    return _Found(
        position=position,
        collection=where.name,
        chunk=request.chunk,
        document_id=document.id,
        link=link_to(document.id, request.chunk),
        passage=ToCite(frontmatter=document.frontmatter, locator=locator),
        locator=locator,
        words=words,
    )


def request_for(target: Target) -> CiteRequest:
    """What a `kennis://` link names, as a request; a project by this
    machine's list. Shared by every client and the window (#625)."""
    from kennis.engine.context.projects import project_named
    from kennis.links import ContextTarget, LinkTarget

    match target:
        case LinkTarget(document_id=document_id, chunk=chunk):
            return CiteRequest(document_id, chunk)
        case ContextTarget(project=project, path=path, chunk=chunk):
            return CiteRequest(path, chunk, bundle=project_named(project).bundle)


def bundle_member(bundle: Path, handle: str) -> tuple[str, Path]:
    """The project's name and the file `handle` names in its bundle, found
    among the files the bundle holds rather than joined onto it, so a path
    from a client climbs nowhere. Shared with `tagging.py` (#625)."""
    from kennis.engine.context.bundle import is_bundle_dir
    from kennis.engine.context.notes import bundle_documents
    from kennis.engine.context.projects import note_project, project_names
    from kennis.engine.errors import ContextNotFound, DocumentNotFound

    if not is_bundle_dir(bundle):
        raise ContextNotFound(f"{bundle} is not a project's context bundle")
    note_project(bundle)
    project = project_names([bundle])[bundle]
    held = {
        path.relative_to(bundle).as_posix(): path for path in bundle_documents(bundle)
    }
    file = held.get(handle)
    if file is None:
        raise DocumentNotFound(
            f"'{handle}' is not in the project {project}'s bundle",
            resolution="kennis context status",
        )
    return project, file


def _found_in_bundle(position: int, request: CiteRequest, bundle: Path) -> _Found:
    """A file in a project's bundle, cited as a note is."""
    from kennis.engine.context.bundle import BUNDLE_DIRNAME
    from kennis.engine.context.groups import project_group
    from kennis.engine.context.index import load_bundle_index

    project, file = bundle_member(bundle, request.handle)
    chunks = load_bundle_index(bundle).chunks if request.chunk is not None else ()
    return _located(
        position,
        request,
        file,
        chunks,
        collection=project_group(project),
        where=f"{project}/{BUNDLE_DIRNAME}/{request.handle}",
        link=context_link(project, request.handle, request.chunk),
    )


def _located(
    position: int,
    request: CiteRequest,
    file: Path,
    chunks: Sequence[Chunk],
    *,
    collection: str,
    where: str,
    link: str,
) -> _Found:
    """A context file cited as a note is, with its chunk's locator read
    from the body its index's offsets address."""
    import yaml

    from kennis.engine.frontmatter import split_frontmatter

    text = file.read_text(encoding="utf-8")
    try:
        frontmatter, body = split_frontmatter(text)
    except yaml.YAMLError:
        # As the loader and the window read it: an unreadable header
        # costs the metadata, not the passage.
        frontmatter, body = {}, text
    title = str(frontmatter.get("title") or file.stem)
    locator: Locator | None = None
    words: str | None = None
    if request.chunk is not None:
        chunk = next(
            (
                one
                for one in chunks
                if one.document_id == request.handle
                and one.chunk_index == request.chunk
            ),
            None,
        )
        if chunk is None:
            raise SearchUnavailable(
                f"'{request.handle}' has no chunk {request.chunk} in its index",
                resolution="kennis context index",
            )
        locator = locator_of(body, chunk.char_start, chunk.char_end)
        words = passage_words(chunk.text)
    return _Found(
        position=position,
        collection=collection,
        chunk=request.chunk,
        document_id=request.handle,
        link=link,
        written=located_note(title, locator, where),
        locator=locator,
        words=words,
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
