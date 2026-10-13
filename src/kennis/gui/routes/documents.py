"""One document read, from a collection or from this project's bundle,
with the passage a search led to marked where the index can place it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import (
    HTMLResponse,
)

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.context.status import bundle_freshness
from kennis.engine.errors import (
    ContextNotFound,
    KennisError,
)
from kennis.engine.history.repository import Repository
from kennis.engine.rag.models import Chunk
from kennis.gui import words
from kennis.gui.pages import (
    ShownDocument,
    shown_bundle_document,
    shown_document,
    shown_matches,
)
from kennis.gui.responses import TEMPLATES, problem_page
from kennis.holdings import (
    document_marks,
    freshness_of,
)
from kennis.render.html import MarkedRange
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

    found = chunk_range(context, collection, document_id, index)
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

    found = chunk_range(resolve_context(), CONTEXT_COLLECTION, relative_path, index)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


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
    try:
        document = shown_document(
            context.corpus_root,
            collection,
            document_id,
            load_remote_images=load_remote,
            marked=marked,
            marks=document_marks(context, collection),
            question=q,
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
            chunks=lambda: document_chunks(context, collection, document.document_id),
        ),
    )


@router.get("/bundle/{relative_path:path}")
def serve_bundle_document(
    request: Request,
    relative_path: str,
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
    """
    bundle = find_bundle()
    if bundle is None:
        return problem_page(request, ContextNotFound())
    marked, withheld = _marked_in_bundle(bundle, relative_path, chunk)
    load_remote = images == "on"
    try:
        document = shown_bundle_document(
            bundle,
            relative_path,
            load_remote_images=load_remote,
            marked=marked,
            question=q,
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
                resolve_context(), CONTEXT_COLLECTION, relative_path
            ),
        ),
    )
