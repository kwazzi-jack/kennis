"""One document read, from a collection or from this project's bundle,
with the passage a search led to marked where the index can place it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
)

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.context.groups import CONTEXT_COLLECTION
from kennis.engine.context.projects import project_named
from kennis.engine.context.status import bundle_freshness
from kennis.engine.errors import (
    KennisError,
)
from kennis.engine.history.freshness import Freshness
from kennis.engine.history.repository import Repository
from kennis.engine.rag.models import Chunk
from kennis.gui import words
from kennis.gui.figures import (
    FIGURE_ROUTE,
    held_figure,
    media_type_of,
    trusted_figure_hosts,
)
from kennis.gui.pages import (
    ShownDocument,
    document_link,
    shown_bundle_document,
    shown_document,
    shown_matches,
)
from kennis.gui.responses import TEMPLATES, problem_page
from kennis.gui.tagged import ShownDocumentTag, document_tags
from kennis.holdings import (
    document_marks,
    freshness_of,
)
from kennis.render.html import Band, MarkedRange, RunHtml, RunOf
from kennis.retrieval import (
    chunk_range,
    document_chunks,
)

router = APIRouter()


def _document_context(
    document: ShownDocument,
    *,
    question: str,
    load_remote: bool,
    withheld: bool,
    placeable: bool | None,
    chunks: Callable[[], list[Chunk]],
    tags: Sequence[ShownDocumentTag],
    back: str,
    reference: str | None = None,
) -> dict[str, object]:
    """What a document page needs, from either store.

    `placeable` is whether the index is in step with the document: None
    when there is no index or nothing was searched, and then there are
    no matches to list. A changed document lists none and says why, by
    the rule that withholds the mark, because its chunks address text
    that has moved. `chunks` is called only when they will be read.
    """
    matches = (
        shown_matches(
            chunks(),
            question=question,
            collection=document.collection,
            document_id=document.document_id,
        )
        if question and placeable
        else ()
    )
    return {
        "document": document,
        "load_remote_images": load_remote,
        "blocked_note": words.IMAGES_BLOCKED,
        "blocked_tip": words.IMAGES_TIP,
        "blocked_action": words.LOAD_IMAGES,
        "mark_withheld": words.MARK_WITHHELD if withheld else None,
        "question": question,
        "search_crumb": words.search_crumb(question) if question else None,
        "matches": matches,
        "matches_withheld": bool(question) and placeable is False,
        "matches_heading": words.matches_heading(question) if question else None,
        "matches_withheld_note": words.MATCHES_WITHHELD,
        "inspector_label": words.INSPECTOR_LABEL,
        "crumbs_label": words.CRUMBS_LABEL,
        "inspector_show": words.INSPECTOR_SHOW,
        "inspector_hide": words.INSPECTOR_HIDE,
        "details_heading": words.DETAILS_HEADING,
        "outline_heading": words.OUTLINE_HEADING,
        "no_headings": words.NO_HEADINGS,
        "no_matches": words.NO_MATCHES,
        # Its tags and the link that tags it whole (#625); a Remove comes
        # back to this page.
        "document_tags": tags,
        "document_link": document_link(document.collection, document.document_id),
        "tags_back": back,
        # The document's full reference, by the person's citation style,
        # for the inspector's Copy reference; None for a project's file,
        # which is cited by its path.
        "reference": reference,
    }


def _marked(
    context: Context, collection: str, document_id: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """The passage to mark, and whether one was withheld.

    Two `None`s that mean different things, which is why the second
    value exists. *No chunk was asked for* - the reader opened the
    document from a listing - should say nothing. *A chunk was asked
    for and cannot be placed* has to say so, because the reader
    followed a link to a passage and would otherwise be left looking
    for it.

    **The offsets belong to the index, so a stale index withholds
    them.** They address the document as it was when it was indexed,
    and once it has changed they point at text that has moved. A mark
    on the wrong paragraph is worse than no mark: it is a confident
    claim, and the reader has no way to tell it is wrong.
    `unverifiable` withholds too - "kennis cannot check" is not
    "kennis checked and it is fine".
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        # Arrived in a query string, so it can be anything. Not an
        # error page: the document is there and is what was asked for.
        return None, False

    freshness = freshness_of(context, Repository(context.corpus_root), collection)
    if freshness is None:
        # No index at all, so there is nothing to place the passage
        # against and nothing was withheld. `chunk_range` would answer
        # None a moment later; asking first keeps it off the disk.
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(context, collection, document_id, index, bundle=None)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


def _marked_in_bundle(
    bundle: Path, relative_path: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """`_marked`, for the scope that is not in the corpus.

    The same three decisions and the same order, over a different
    index and a different freshness: `bundle_freshness` answers the
    question `freshness_of` answers for a collection, and cannot be
    the same function because a bundle has no git history to compare
    against. Written out rather than abstracted over the two, because
    the two only look alike - the shared part is three lines and the
    differing part is every value in them.
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        return None, False

    freshness = bundle_freshness(bundle)
    if freshness is None:
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(
        resolve_context(), CONTEXT_COLLECTION, relative_path, index, bundle=bundle
    )
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


@router.get(FIGURE_ROUTE + "/{path:path}")
def serve_figure(path: str) -> FileResponse:
    """One image a document's markdown links, as its file (#642).

    `no-cache` asks the browser to check before reusing its copy, which a
    `FileResponse` answers from the file's size and time: a kept image is
    named by its content, but one a person put beside a document is not.
    """
    figure = held_figure(existing_corpus().corpus_root, path)
    if figure is None:
        raise HTTPException(status_code=404)
    return FileResponse(
        figure,
        media_type=media_type_of(figure),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-cache",
        },
    )


@router.get("/document/{collection}/{document_id}")
def serve_document(
    request: Request,
    collection: str,
    document_id: str,
    images: str = "",
    chunk: str = "",
    q: str = "",
) -> HTMLResponse:
    load_remote = images == "on"
    context = existing_corpus()
    marked, withheld = _marked(context, collection, document_id, chunk)
    tags = _tags_or_none(
        lambda: document_tags(context, document=document_id, project=None, bundle=None)
    )
    try:
        document = shown_document(
            context.corpus_root,
            collection,
            document_id,
            load_remote_images=load_remote,
            marked=marked,
            marks=document_marks(context, collection),
            question=q,
            bands=_tag_bands(
                tags,
                in_step=lambda: _in_step(
                    freshness_of(context, Repository(context.corpus_root), collection)
                ),
                chunks=lambda: document_chunks(
                    context, collection, document_id, bundle=None
                ),
            ),
            run=_tag_run(tags),
            trusted_hosts=trusted_figure_hosts(),
        )
    except KennisError as error:
        return problem_page(request, error)
    freshness = (
        freshness_of(context, Repository(context.corpus_root), collection)
        if q
        else None
    )
    return TEMPLATES.TemplateResponse(
        request,
        "document.html",
        _document_context(
            document,
            question=q,
            load_remote=load_remote,
            withheld=withheld,
            placeable=None if freshness is None else freshness.state == "in step",
            chunks=lambda: document_chunks(
                context, collection, document.document_id, bundle=None
            ),
            tags=tags,
            back=_this_page(request),
            reference=_reference_of(context, document.document_id),
        ),
    )


def _reference_of(context: Context, document_id: str) -> str | None:
    """The document's reference as the citation style writes it, or None
    when it cannot be written: the page is still worth showing."""
    from kennis.citing import CiteRequest, cite

    try:
        cited = cite(context, [CiteRequest(document_id)])
    except KennisError:
        return None
    return cited.citations[0].reference if cited.citations else None


def _in_step(freshness: Freshness | None) -> bool:
    """Whether an index's offsets address the document as it is now."""
    return freshness is not None and freshness.state == "in step"


def _tag_bands(
    tags: Sequence[ShownDocumentTag],
    *,
    in_step: Callable[[], bool],
    chunks: Callable[[], list[Chunk]],
) -> list[Band]:
    """Each tagged passage's range, carrying its tags (#50).

    By the rule that withholds a mark: a passage placed by the index is
    drawn over the offsets that index recorded, which address the document
    only while the index is in step with it. Neither the freshness nor the
    chunks are read when nothing is tagged by passage.
    """
    by_chunk: dict[int, set[str]] = {}
    for tagged in tags:
        if tagged.chunk is not None and tagged.placed:
            by_chunk.setdefault(tagged.chunk, set()).add(tagged.name)
    if not by_chunk or not in_step():
        return []
    return [
        Band(chunk.char_start, chunk.char_end, frozenset(by_chunk[chunk.chunk_index]))
        for chunk in chunks()
        if chunk.chunk_index in by_chunk
    ]


def _tag_run(tags: Sequence[ShownDocumentTag]) -> RunOf:
    """What is drawn around a run of blocks carrying `names`: its chips in
    name order, the first one's colour down the margin."""
    by_name = {tagged.name: tagged for tagged in reversed(tags)}
    template = TEMPLATES.get_template("tag-run.html")

    def drawn(names: frozenset[str]) -> RunHtml:
        chips = [by_name[name] for name in sorted(names)]
        label = words.tags_on_passage([chip.name for chip in chips])
        return RunHtml(template.render(chips=chips, label=label).strip(), "</div>")

    return drawn


def _tags_or_none(
    read: Callable[[], list[ShownDocumentTag]],
) -> list[ShownDocumentTag]:
    """The document's tags, or none when a tags file cannot be read: the
    document is still worth showing, and `kennis tags` says what is wrong."""
    try:
        return read()
    except KennisError:
        return []


def _this_page(request: Request) -> str:
    """This page's address within the window, for a Remove to return to."""
    query = request.url.query
    return request.url.path + (f"?{query}" if query else "")


def _marked_in(chunks: list[Chunk], chunk: str) -> MarkedRange | None:
    try:
        wanted = int(chunk)
    except ValueError:
        return None
    for found in chunks:
        if found.chunk_index == wanted:
            return MarkedRange(
                start=found.char_start, end=found.char_end, anchor=f"chunk-{wanted}"
            )
    return None


@router.get("/bundle/{relative_path:path}")
def serve_bundle_document(
    request: Request,
    relative_path: str,
    project: str = "",
    images: str = "",
    chunk: str = "",
    q: str = "",
) -> HTMLResponse:
    """One note out of this project's bundle.

    A separate route from `/document/...` because it reads a
    separate store: the bundle is in the user's repository and is
    not a collection of the corpus. Linking a context hit into
    the corpus route is what answered a quarter of all searches
    with "unknown collection". Concern #332.

    The project is named in the query, because the window belongs to no
    project and a name may hold a `/` (14g, #512).
    """
    try:
        bundle = project_named(project).bundle
    except KennisError as error:
        return problem_page(request, error)
    marked, withheld = _marked_in_bundle(bundle, relative_path, chunk)
    load_remote = images == "on"
    tags = _tags_or_none(
        lambda: document_tags(
            existing_corpus(), document=relative_path, project=project, bundle=bundle
        )
    )
    try:
        document = shown_bundle_document(
            bundle,
            relative_path,
            project=project,
            load_remote_images=load_remote,
            marked=marked,
            question=q,
            bands=_tag_bands(
                tags,
                in_step=lambda: _in_step(bundle_freshness(bundle)),
                chunks=lambda: document_chunks(
                    resolve_context(), CONTEXT_COLLECTION, relative_path, bundle=bundle
                ),
            ),
            run=_tag_run(tags),
            trusted_hosts=trusted_figure_hosts(),
        )
    except KennisError as error:
        return problem_page(request, error)
    freshness = bundle_freshness(bundle) if q else None
    return TEMPLATES.TemplateResponse(
        request,
        "document.html",
        _document_context(
            document,
            question=q,
            load_remote=load_remote,
            withheld=withheld,
            placeable=None if freshness is None else freshness.state == "in step",
            chunks=lambda: document_chunks(
                resolve_context(), CONTEXT_COLLECTION, relative_path, bundle=bundle
            ),
            tags=tags,
            back=_this_page(request),
        ),
    )
