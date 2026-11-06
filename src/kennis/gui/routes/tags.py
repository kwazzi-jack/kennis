"""Tags in the window (#625): every tag, one tag's page, the dialog that
tags a passage or a document, and removing a tag.

A target is named by its `kennis://` link in every form, as the hit card and
the inspector carry it. Tagging writes one small file and answers at once,
as Forget does; `tagging.change_tags` holds its own lock, so a tag written
here cannot interleave with one from the command line or an agent.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from kennis.citing import request_for
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError
from kennis.engine.tags import (
    TAG_COLOURS,
    colour_of,
    is_hex_colour,
    split_tag_names,
    tag_name,
)
from kennis.gui import words
from kennis.gui.pages import ShownOutcome
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    action_page,
    from_htmx,
    problem_page,
    refused_a_post,
    refused_in_the_form,
)
from kennis.gui.tagged import (
    chosen_colours_here,
    listings,
    pane_tags,
    present_bundles,
    shown_tagged,
    tag_href,
    tags_in_use,
)
from kennis.gui.theme import TAG_COLOURS as TAG_COLOUR_VALUES
from kennis.links import target_of
from kennis.tagging import Tagged, change_tags

router = APIRouter()

# The colour form's choice that sends its picker's value instead (#629).
_OWN_COLOUR = "own"

# Where a refusal in the tag dialog is answered, above its still-filled field.
_OUTCOME = "#tag-outcome"


@router.get("/tags")
def serve_tags(request: Request, tag: str = "") -> HTMLResponse:
    """Every tag with its count, or, with `tag`, what that tag holds."""
    context = existing_corpus()
    if not tag:
        return TEMPLATES.TemplateResponse(
            request,
            "tags.html",
            {"tags": pane_tags(context), "tag": None, "tagged": []},
        )
    try:
        name = tag_name(tag)
        listing = next((one for one in listings(context) if one.name == name), None)
        if listing is None:
            raise KennisError(f"nothing is tagged {name}", resolution="kennis tags")
    except KennisError as error:
        return problem_page(request, error)
    chosen = chosen_colours_here(context)
    return TEMPLATES.TemplateResponse(
        request,
        "tags.html",
        {
            "tags": (),
            "tag": name,
            "tagged": shown_tagged(listing),
            "search_href": f"/?tag={name}",
            "back": tag_href(name),
            "colour": colour_of(name, chosen),
            "chosen_colour": chosen.get(name, "auto"),
            "chosen_hex": chosen[name] if is_hex_colour(chosen.get(name, "")) else "",
            "derived_hex": TAG_COLOUR_VALUES[colour_of(name, {})]["light"].lower(),
            "colour_own": words.TAG_COLOUR_OWN,
            "colour_choices": (
                ("auto", words.TAG_COLOUR_AUTOMATIC),
                *((one, words.TAG_COLOUR_NAMES[one]) for one in TAG_COLOURS),
            ),
            "colour_label": words.TAG_COLOUR_LABEL,
            "colour_set": words.TAG_COLOUR_SET,
            "derived_colour": colour_of(name, {}),
        },
    )


@router.get("/tags/add")
def ask_for_tags(request: Request, link: str = "") -> HTMLResponse:
    """The dialog that tags the passage or document `link` names."""
    context = existing_corpus()
    try:
        title = _title_of(link)
    except KennisError as error:
        return problem_page(request, error)
    return action_page(
        request,
        "/tags/add",
        "forms/tag.html",
        {
            "link": link,
            "tagging": words.tagging(title),
            "suggestions": tags_in_use(context),
            "outcome": None,
        },
    )


@router.post("/tags/add")
def add_tags(request: Request, form: PostedForm) -> Response:
    link = str(form.get("link") or "")
    try:
        names = split_tag_names(str(form.get("names") or ""))
        tagged = change_tags(
            existing_corpus(), [request_for(target_of(link))], names, remove=False
        )
    except KennisError as error:
        return _refused(request, str(error), error.resolution)
    if tagged.refused:
        refusal = tagged.refused[0]
        return _refused(request, refusal.message, refusal.resolution)
    if not from_htmx(request):
        return RedirectResponse(tag_href(names[0]), status_code=303)
    return TEMPLATES.TemplateResponse(
        request, "outcome.html", {"outcome": _outcome(tagged), "state": ""}
    )


@router.post("/tags/remove")
def remove_tag(request: Request, form: PostedForm) -> Response:
    """Take one tag from one target, then back to the page it was taken on.

    Untagging needs no index, so a detached passage is removed as the page
    names it."""
    link = str(form.get("link") or "")
    back = str(form.get("back") or "")
    try:
        name = tag_name(str(form.get("tag") or ""))
        change_tags(
            existing_corpus(), [request_for(target_of(link))], [name], remove=True
        )
    except KennisError as error:
        return refused_a_post(request, str(error), resolution=error.resolution)
    # Only a path in this window: a `back` naming another host is refused
    # in favour of the tag's own page.
    if not back.startswith("/") or back.startswith("//"):
        back = tag_href(name)
    return RedirectResponse(back, status_code=303)


@router.post("/tags/colour")
def colour_tag(request: Request, form: PostedForm) -> Response:
    """Choose a tag's colour, or go back to the one from its name (#627),
    in the corpus and every project that holds it; then its page again."""
    from kennis.tagging import colour_tags

    colour = str(form.get("colour") or "")
    picked = str(form.get("hex") or "")
    if colour == _OWN_COLOUR or (picked and picked != form.get("drawn-hex")):
        colour = picked
    try:
        name = tag_name(str(form.get("tag") or ""))
        colour_tags(
            existing_corpus(),
            [name],
            None if colour in ("", "auto") else colour,
            present_bundles(),
        )
    except KennisError as error:
        return refused_a_post(request, str(error), resolution=error.resolution)
    if from_htmx(request):
        return Response(headers={"HX-Refresh": "true"})
    return RedirectResponse(tag_href(name), status_code=303)


def _refused(request: Request, problem: str, resolution: str | None) -> Response:
    if from_htmx(request):
        return refused_in_the_form(request, _OUTCOME, problem)
    return refused_a_post(request, problem, resolution=resolution)


def _outcome(tagged: Tagged) -> ShownOutcome:
    (change,) = tagged.changes
    title = change.title or change.handle
    if change.changed:
        return ShownOutcome(
            message=words.tagged_with(title, change.changed), role="role-added"
        )
    return ShownOutcome(
        message=words.already_tagged_with(title, change.unchanged),
        role="role-muted",
    )


def _title_of(link: str) -> str:
    """What the dialog says it is tagging: the document's title."""
    from kennis.citing import bundle_member
    from kennis.finding import resolve_document
    from kennis.tagging import bundle_title

    request = request_for(target_of(link))
    if request.bundle is not None:
        _, file = bundle_member(request.bundle, request.handle)
        return bundle_title(file)
    _, document = resolve_document(existing_corpus(), request.handle, None)
    return document.frontmatter.title


__all__ = ["router"]
