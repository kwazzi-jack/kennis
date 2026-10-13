"""The corpus browsed: its holdings, a collection's page, the pane's tree,
and a move made from it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from kennis.context import existing_corpus
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import (
    KennisError,
    UnknownCollection,
)
from kennis.engine.history.outofband import OutOfBandChange
from kennis.gui import words
from kennis.gui.pages import (
    shown_groups,
    shown_rows,
    shown_tree,
)
from kennis.gui.pane import bundle_folders
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    frame,
    from_htmx,
    problem_page,
    refused,
    refused_a_post,
    written,
)
from kennis.holdings import (
    holdings,
    installed_packs,
)
from kennis.operations import (
    move_a_document,
)
from kennis.render.packs import describe_holdings
from kennis.render.words import describe_change

router = APIRouter()


def _tree(
    request: Request,
    collection: str,
    *,
    problem: str | None = None,
    notes: tuple[str, ...] = (),
    moved: bool = False,
) -> HTMLResponse:
    """One collection's branch of the pane, with a refusal at its head, or
    what a move from it put back."""
    return TEMPLATES.TemplateResponse(
        request,
        "tree.html",
        {
            "tree": shown_tree(existing_corpus(), collection),
            "problem": problem,
            "notes": notes,
            "moved": moved,
            "attention_only": words.ATTENTION_ONLY,
            "menu_open": words.MENU_OPEN,
            "menu_move": words.MENU_MOVE,
            "menu_add_here": words.MENU_ADD_HERE,
            "menu_index": words.MENU_INDEX,
            "move_group_label": words.MOVE_GROUP_LABEL,
            "move_group_empty": words.MOVE_GROUP_EMPTY,
            "menu_for": words.menu_for,
        },
    )


@router.get("/corpus")
def serve_corpus(request: Request) -> HTMLResponse:
    context = existing_corpus()
    held = holdings(context)
    return TEMPLATES.TemplateResponse(
        request,
        "corpus.html",
        {
            "rows": shown_rows(held),
            "holdings_columns": words.HOLDINGS_COLUMNS,
            "empty": not any(holding.documents for holding in held),
            "packs": describe_holdings(installed_packs(context)),
            "nothing_held": words.NOTHING_HELD,
            "no_packs": words.NO_PACKS,
            **frame(context),
        },
    )


@router.get("/collection/{collection}")
def serve_collection(request: Request, collection: str) -> HTMLResponse:
    context = existing_corpus()
    if collection not in COLLECTION_NAMES:
        return problem_page(
            request, UnknownCollection(words.unknown_collection(collection))
        )
    groups, unreadable = shown_groups(context, collection)
    held = next(h for h in holdings(context) if h.collection == collection)
    return TEMPLATES.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": collection,
            "groups": groups,
            "summary": words.describe_count(held),
            "unreadable": words.unreadable_note(unreadable),
            **frame(context),
        },
    )


@router.get("/tree/{collection}")
def serve_tree(request: Request, collection: str) -> HTMLResponse:
    """One collection's documents, or the bundle's, for the pane.

    Fetched when the reader opens it, never drawn with the page:
    every document costs about 0.7 ms to list, which on every page
    load would be most of a second at a thousand documents.
    """
    if collection == CONTEXT_COLLECTION:
        bundle = find_bundle()
        folders = [] if bundle is None else bundle_folders(bundle)
        return TEMPLATES.TemplateResponse(
            request, "tree-context.html", {"folders": folders}
        )
    if collection not in COLLECTION_NAMES:
        return refused(request, words.unknown_collection(collection))
    return _tree(request, collection)


@router.post("/move")
def move_from_the_tree(request: Request, form: PostedForm) -> Response:
    """Refile one document into the group typed in its menu.

    htmx gets the collection's branch redrawn, so the reader sees the
    document where it now is; a plain form returns to the collection's
    page. A refusal - a group that leaves the collection, a docs page,
    a busy corpus - is drawn at the head of the same branch.
    """
    collection = str(form.get("collection") or "")
    if collection not in COLLECTION_NAMES:
        return refused_a_post(request, words.unknown_collection(collection))
    handle = str(form.get("document") or "")
    group = str(form.get("group") or "").strip()
    context = existing_corpus()
    held = Collection(root=context.corpus_root, name=collection)
    restored: list[OutOfBandChange] = []
    try:
        move_a_document(
            context, held, held.resolve(handle), group=group, restored=restored
        )
    except KennisError as error:
        if from_htmx(request):
            return _tree(request, collection, problem=str(error))
        return refused_a_post(request, str(error), resolution=error.resolution)
    if from_htmx(request):
        notes = tuple(describe_change(change) for change in restored)
        return written(_tree(request, collection, notes=notes, moved=True))
    return RedirectResponse(f"/collection/{collection}", status_code=303)
