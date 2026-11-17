"""Annotating a selection of a document's text, and changing or removing an
annotation, in the window (#50; sketch 2026-11-16-annotate-selection).

A selection is made on a document's page and found again in its markdown
(`POST /annotate/located`, which writes nothing); the dialog that comes back
posts the found range (`POST /annotations`). An annotation is opened, saved
and deleted by its id, in its project's store or the corpus's. After a write
the page the dialog was opened on draws its text and inspector again, so
the reader stays where they were.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from kennis.context import existing_corpus
from kennis.engine.annotations import Span, selection_in
from kennis.engine.errors import KennisError
from kennis.engine.tags import tag_name
from kennis.gui import words
from kennis.gui.outcomes import ShownOutcome
from kennis.gui.pages import DOCUMENT_ANNOTATIONS, DOCUMENT_TAGS, DOCUMENT_TEXT
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    action_page,
    current_page,
    from_htmx,
    problem_page,
    refused_a_post,
    refused_in_the_form,
)
from kennis.gui.tagged import tags_in_use
from kennis.render.tags import opening_words
from kennis.tagging import (
    Shown,
    annotate,
    delete_annotation,
    find_annotation,
    revise_annotation,
    shown_body,
)

router = APIRouter()

# The most text a selection may hold: an annotation is a passage, and the
# dialog is opened by a request that carries it.
MOST_SELECTED: Final = 4000
_OUTCOME: Final = "#annotate-outcome"


def _shown(form: PostedForm) -> Shown:
    """The document the form names: a project's file, or a corpus document
    by its collection."""
    document = str(form.get("document") or "")
    project = str(form.get("project") or "")
    if not document:
        raise KennisError("no document was named", resolution="open the document again")
    if project:
        return Shown(document, bundle=_bundle_of(project))
    return Shown(document, collection=str(form.get("collection") or "") or None)


def _bundle_of(project: str) -> Path | None:
    """The bundle of the listed project named `project`; None for none."""
    from kennis.engine.context.projects import project_named

    return project_named(project).bundle if project else None


def _span(text: str) -> Span:
    """A block's `data-source`, two offsets."""
    parts = text.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise KennisError(
            "the selection's place in the document was not understood",
            resolution="select the text again",
        )
    start, end = (int(part) for part in parts)
    return Span(start, end)


def _tags(text: str) -> tuple[str, ...]:
    """Comma-separated tags as typed, blanks left out: an annotation may
    carry none."""
    return tuple(
        dict.fromkeys(tag_name(part) for part in text.split(",") if part.strip())
    )


def _back(form: PostedForm) -> str:
    """Where a plain form returns: a path in this window, or the tags."""
    back = str(form.get("back") or "")
    return back if back.startswith("/") and not back.startswith("//") else "/tags"


def _path_of(address: str) -> str:
    """An address's path and query, to come back to it within the window."""
    from urllib.parse import urlsplit

    parts = urlsplit(address)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _redraws(request: Request) -> list[tuple[str, str, str]]:
    """The text, the annotations and the tags of the page the dialog was
    opened on, asked for again (#49); none when the page is not known."""
    page = current_page(request)
    if page is None:
        return []
    return [
        (element, page, f"#{element}")
        for element in (DOCUMENT_TEXT, DOCUMENT_ANNOTATIONS, DOCUMENT_TAGS)
    ]


def _answered(request: Request, form: PostedForm, message: str) -> Response:
    """A write's answer: in the dialog with the page's parts redrawn, or
    back to the page for a plain form."""
    if not from_htmx(request):
        return RedirectResponse(_back(form), status_code=303)
    return TEMPLATES.TemplateResponse(
        request,
        "outcome.html",
        {
            "outcome": ShownOutcome(message=message, role="role-added"),
            "state": "",
            "redraws": _redraws(request),
        },
    )


def _refused(request: Request, error: KennisError) -> Response:
    if from_htmx(request):
        return refused_in_the_form(request, _OUTCOME, str(error))
    return refused_a_post(request, str(error), resolution=error.resolution)


@router.post("/annotate/located")
def locate_selection(request: Request, form: PostedForm) -> HTMLResponse:
    """The dialog that annotates the selection the page posted, found in
    the document's markdown. Writes nothing."""
    text = str(form.get("text") or "")
    try:
        shown = _shown(form)
        first = _span(str(form.get("first") or ""))
        last = _span(str(form.get("last") or ""))
        body = shown_body(existing_corpus(), shown).body
    except KennisError as error:
        return problem_page(request, error)
    span = (
        None
        if len(text) > MOST_SELECTED
        else selection_in(body, first, last, text, str(form.get("before") or ""))
    )
    exact = "" if span is None else body[span.start : span.end]
    return action_page(
        request,
        "/annotate",
        "forms/annotate.html",
        {
            "found": span is not None,
            "not_found": words.SELECTION_TOO_LONG
            if len(text) > MOST_SELECTED
            else words.SELECTION_NOT_FOUND,
            "quote": opening_words(exact) if exact else "",
            "start": 0 if span is None else span.start,
            "end": 0 if span is None else span.end,
            "exact": exact,
            "document": shown.document,
            "collection": shown.collection or "",
            "project": str(form.get("project") or ""),
            "back": current_page(request) or "",
            "suggestions": tags_in_use(existing_corpus()),
            "outcome": None,
        },
    )


@router.post("/annotations")
def add_annotation(request: Request, form: PostedForm) -> Response:
    """Annotate the range the dialog found, with its tags and comment."""
    try:
        start = int(str(form.get("start") or "-1"))
        end = int(str(form.get("end") or "-1"))
        annotate(
            existing_corpus(),
            _shown(form),
            start=start,
            end=end,
            exact=str(form.get("exact") or ""),
            tags=_tags(str(form.get("tags") or "")),
            comment=str(form.get("comment") or ""),
        )
    except ValueError:
        return _refused(
            request,
            KennisError(
                "the selection's place was not understood",
                resolution="select the text again",
            ),
        )
    except KennisError as error:
        return _refused(request, error)
    return _answered(request, form, words.ANNOTATION_SAVED)


@router.get("/annotations/{annotation_id}")
def ask_about_annotation(
    request: Request, annotation_id: str, project: str = ""
) -> HTMLResponse:
    """The dialog that changes or deletes one annotation."""
    context = existing_corpus()
    try:
        annotation = find_annotation(context, annotation_id, bundle=_bundle_of(project))
    except KennisError as error:
        return problem_page(request, error)
    selector = annotation.selector
    return action_page(
        request,
        "/annotations",
        "forms/annotation.html",
        {
            "annotation": annotation,
            "quote": None if selector is None else opening_words(selector.exact),
            "tags": ", ".join(annotation.tags),
            "comment": annotation.comment or "",
            "project": project,
            "back": current_page(request)
            or _path_of(request.headers.get("referer", "")),
            "suggestions": tags_in_use(context),
            "outcome": None,
        },
    )


@router.post("/annotations/{annotation_id}")
def save_annotation(request: Request, annotation_id: str, form: PostedForm) -> Response:
    """Give the annotation the tags and comment the dialog holds."""
    try:
        revise_annotation(
            existing_corpus(),
            annotation_id,
            bundle=_bundle_of(str(form.get("project") or "")),
            tags=_tags(str(form.get("tags") or "")),
            comment=str(form.get("comment") or ""),
        )
    except KennisError as error:
        return _refused(request, error)
    return _answered(request, form, words.ANNOTATION_SAVED)


@router.post("/annotations/{annotation_id}/delete")
def remove_annotation(
    request: Request, annotation_id: str, form: PostedForm
) -> Response:
    """Delete the annotation, its tags and comment with it."""
    try:
        delete_annotation(
            existing_corpus(),
            annotation_id,
            bundle=_bundle_of(str(form.get("project") or "")),
        )
    except KennisError as error:
        return _refused(request, error)
    return _answered(request, form, words.ANNOTATION_DELETED)


__all__ = ["MOST_SELECTED", "router"]
