"""The Add dialog: its tabs, the previews and checks it asks for as it is
filled in, the chooser for a path on this computer, and the add itself.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response
from fastapi.datastructures import FormData
from fastapi.responses import (
    HTMLResponse,
)

from kennis.context import Context, existing_corpus
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.preview import check_lines, preview_paper, preview_site
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.history.outofband import OutOfBandChange
from kennis.gui import words
from kennis.gui.adding import (
    FIRST_BLOCKS,
    FIXED_COLLECTIONS,
    add_fields,
    add_kind,
    add_tabs,
    chooser_target,
    destination_of,
    filled,
    listing_of,
    shown_checks,
    shown_paper_preview,
    shown_site_preview,
)
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    action_page,
    frame,
    from_htmx,
    refused,
    refused_a_post,
)
from kennis.gui.routes.jobs import started
from kennis.operations import (
    GroupBlock,
    add_documents,
    add_in_groups,
)

router = APIRouter()


def _lines(given: str) -> list[str]:
    """One identifier per line, blank lines ignored.

    A textarea rather than a single field because a batch is the
    ordinary case - a folder of papers arrives as a list - and because
    a space-separated field cannot hold a path with a space in it.
    """
    return [line.strip() for line in given.splitlines() if line.strip()]


def _add_context(
    asked: str, given: Mapping[str, str] | None = None
) -> dict[str, object]:
    """One tab of the Add dialog, with any place it was opened on filled in."""
    kind = add_kind(asked)
    return {
        "kind": kind,
        "tabs": add_tabs(kind),
        "preamble": words.ADD_PREAMBLES[kind],
        "fields": filled(
            add_fields(
                kind, default_group=existing_corpus().settings.corpus.default_group
            ),
            given or {},
        ),
        "fixed_collection": FIXED_COLLECTIONS.get(kind),
        "collections": COLLECTION_NAMES,
        "first_blocks": FIRST_BLOCKS,
        "add_action": words.ADD_ACTIONS[kind],
        "adds_to": words.ADDS_TO,
        "cancel": words.CANCEL,
        "destination": destination_of(kind, given or {}),
    }


def _group_blocks(form: FormData) -> list[GroupBlock] | str:
    """The Several by group tab's blocks that have lines, or why not.

    A block with no lines is skipped - two are drawn whether or not both
    are wanted - and a block with lines and no name is refused, because
    the name is the point of the tab.
    """
    numbers = sorted(
        int(key.removeprefix("lines-"))
        for key in form
        if key.startswith("lines-") and key.removeprefix("lines-").isdigit()
    )
    blocks: list[GroupBlock] = []
    for number in numbers:
        identifiers = _lines(str(form.get(f"lines-{number}") or ""))
        if not identifiers:
            continue
        name = str(form.get(f"group-{number}") or "").strip()
        if not name:
            return words.GROUP_NEEDS_A_NAME
        destination = str(form.get(f"collection-{number}") or "")
        if not destination:
            return words.CHOOSE_A_COLLECTION
        if destination not in COLLECTION_NAMES:
            return words.unknown_collection(destination)
        blocks.append(
            GroupBlock(
                collection=destination, group=name, identifiers=tuple(identifiers)
            )
        )
    return blocks


def _count(form: FormData, name: str, default: int) -> int | str:
    """A whole-number field, its default when empty, or why not."""
    given = str(form.get(name) or "").strip()
    if not given:
        return default
    if not given.isdigit() or int(given) < 1:
        return words.not_a_count(words.FIELD_LABELS[name], given)
    return int(given)


def _add_options(context: Context, form: FormData) -> AddOptions | str:
    """The engine's options, from the form and the settings behind it,
    or the sentence refusing a field that cannot be one.

    The settings supply what the form does not ask: a default group, a
    conversion batch size and the politeness delay are configuration
    rather than per-add decisions, and putting them on the page would
    invite changing them per add.
    """
    defaults = AddOptions()
    max_pages = _count(form, "max_pages", defaults.max_pages)
    if isinstance(max_pages, str):
        return max_pages
    max_depth = _count(form, "max_depth", defaults.max_depth)
    if isinstance(max_depth, str):
        return max_depth
    identifier = str(form.get("identifier") or "") or None
    return AddOptions(
        max_pages=max_pages,
        max_depth=max_depth,
        title=str(form.get("title") or "") or None,
        group=str(form.get("group") or "")
        or context.settings.corpus.default_group
        or None,
        keep_original=context.settings.corpus.keep_original,
        identifier=identifier,
        citekey=str(form.get("citekey") or "") or None,
        project=str(form.get("project") or "") or None,
        batch_size=context.settings.conversion.batch_size,
        request_delay_seconds=context.settings.literature.request_delay,
        extra_file_types=(),
    )


@router.get("/add")
def serve_add_form(
    request: Request,
    kind: str = "",
    collection: str = "",
    group: str = "",
    project: str = "",
) -> HTMLResponse:
    # The place is filled in when the dialog is opened from the tree's
    # Add here; choosing the row was the reader choosing it (#431).
    given = {"collection": collection, "group": group, "project": project}
    return action_page(request, "/add", "forms/add.html", _add_context(kind, given))


@router.get("/add/block")
def serve_add_block(request: Request, index: int = 1) -> HTMLResponse:
    """One more group, and the button that asks for the one after."""
    return TEMPLATES.TemplateResponse(
        request,
        "forms/add-blocks.html",
        {"index": max(1, min(index, 999)), "collections": COLLECTION_NAMES},
    )


# Plain `def`, not `async`: a preview may ask arXiv or probe a site,
# and a blocking request inside an `async` route would stall every
# other request until it answered. FastAPI runs these on a thread.
@router.get("/add/preview/paper")
def preview_a_paper(
    request: Request, identifiers: str = "", citekey: str = "", title: str = ""
) -> HTMLResponse:
    first = next(iter(_lines(identifiers)), "")
    papers = Collection(root=existing_corpus().corpus_root, name="literature")
    preview = preview_paper(
        papers, first, citekey=citekey.strip() or None, title=title.strip() or None
    )
    return TEMPLATES.TemplateResponse(
        request, "forms/add-preview.html", {"lines": shown_paper_preview(preview)}
    )


@router.get("/add/preview/site")
def preview_a_site(
    request: Request, identifiers: str = "", project: str = "", probe: str = ""
) -> HTMLResponse:
    first = next(iter(_lines(identifiers)), "")
    probed = bool(probe) and bool(first)
    preview = preview_site(first, project=project.strip() or None, probe=probed)
    return TEMPLATES.TemplateResponse(
        request,
        "forms/add-preview.html",
        {"lines": shown_site_preview(preview, probed=probed)},
    )


@router.get("/add/check")
def check_a_block(request: Request, index: int = 1) -> HTMLResponse:
    """Each line of one group, as its own tab would recognise it."""
    asked = request.query_params
    destination = asked.get(f"collection-{index}", "notes")
    if destination not in COLLECTION_NAMES:
        destination = "notes"
    target = Collection(root=existing_corpus().corpus_root, name=destination)
    checks = check_lines(target, _lines(asked.get(f"lines-{index}", "")))
    return TEMPLATES.TemplateResponse(
        request, "forms/add-check.html", {"checks": shown_checks(checks)}
    )


@router.get("/skip")
def serve_skip(request: Request) -> HTMLResponse:
    """What Skip beside a refusal's repairs amounts to: nothing.

    No engine change and nothing written - the item was already
    refused and the rest of the add went on. A GET, because it
    changes nothing, and a page without a script so the button is
    never dead.
    """
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "skipped.html", {})
    return TEMPLATES.TemplateResponse(
        request, "skipped-page.html", frame(existing_corpus())
    )


@router.get("/browse")
def serve_chooser(
    request: Request, target: str = "", path: str = "", folders: str = ""
) -> HTMLResponse:
    """One folder of this computer, for a field to take a path from.

    Read-only and names only, under the same token as every route.
    Without a script it is a page of paths to copy, because nothing
    else can put one into a form.
    """
    chosen = chooser_target(target)
    if chosen is None:
        return HTMLResponse(words.NOT_A_FIELD, status_code=400)
    wants_folders = bool(folders)
    context = {
        "target": chosen,
        "folders": wants_folders,
        "listing": listing_of(path, target=chosen, folders=wants_folders),
    }
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "chooser.html", context)
    return TEMPLATES.TemplateResponse(
        request,
        "chooser-page.html",
        {**context, "page": True, **frame(existing_corpus())},
    )


# Said by a refusal answered inside the Add dialog, so `dialog.js`
# leaves the dialog open with what was typed still in it.
REFUSED_HEADER = "X-Kennis-Refused"


def _refused_in_the_form(request: Request, problem: str) -> HTMLResponse:
    """A refusal the reader can correct, answered above the still-filled
    fields rather than in the strip with the dialog closed behind it.

    Without a script there is no dialog to keep, so it is the refusal
    page every plain form gets.
    """
    if not from_htmx(request):
        return refused_a_post(request, problem)
    answer = refused(request, problem)
    answer.headers["HX-Retarget"] = "#add-problem"
    answer.headers["HX-Reswap"] = "innerHTML"
    answer.headers[REFUSED_HEADER] = "true"
    return answer


@router.post("/add")
def start_add(request: Request, form: PostedForm) -> Response:
    """Start an add and answer with somewhere to watch it.

    Answers at once rather than when the work is done: one PDF is
    twenty seconds of MinerU and a documentation crawl is minutes,
    and a POST that returns at the end is a browser that appears to
    have hung.
    """
    context = existing_corpus()
    options = _add_options(context, form)
    if isinstance(options, str):
        return _refused_in_the_form(request, options)
    if form.get("kind") == "group":
        blocks = _group_blocks(form)
        if isinstance(blocks, str):
            return _refused_in_the_form(request, blocks)
        if not blocks:
            return _refused_in_the_form(request, words.NOTHING_TO_ADD)
        restored: list[OutOfBandChange] = []
        return started(
            request,
            "add",
            lambda events: add_in_groups(
                context, blocks, options, events=events, restored=restored
            ),
            restored=restored,
        )
    identifiers = _lines(str(form.get("identifiers") or ""))
    destination = str(form.get("collection") or "")
    if not identifiers:
        return _refused_in_the_form(request, words.NOTHING_TO_ADD)
    if not destination:
        return _refused_in_the_form(request, words.CHOOSE_A_COLLECTION)
    if destination not in COLLECTION_NAMES:
        return _refused_in_the_form(request, words.unknown_collection(destination))
    put_back: list[OutOfBandChange] = []
    return started(
        request,
        "add",
        lambda events: add_documents(
            context,
            destination,
            identifiers,
            options,
            events=events,
            restored=put_back,
        ),
        restored=put_back,
    )
