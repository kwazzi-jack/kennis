"""Writing a note, into the corpus or into this project's bundle."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request
from fastapi.responses import (
    HTMLResponse,
)

from kennis.context import existing_corpus
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.errors import (
    CorpusBusy,
    KennisError,
)
from kennis.engine.history.outofband import OutOfBandChange
from kennis.gui import words
from kennis.gui.pages import (
    ShownOutcome,
)
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    action_page,
    frame,
    from_htmx,
    written,
)
from kennis.render.words import describe_change
from kennis.writing import write_context_note, write_note

router = APIRouter()


def _remember_context(outcome: ShownOutcome | None) -> dict[str, object]:
    """What the writing page needs, with or without an answer yet."""
    return {
        "outcome": outcome,
        "preamble": words.REMEMBER_PREAMBLE,
        "placeholder": words.REMEMBER_PLACEHOLDER,
        "title_hint": words.TITLE_HINT,
        "group_hint": words.GROUP_HINT,
        "action": words.REMEMBER_ACTION,
        **frame(existing_corpus()),
    }


def _remembered(
    text: str, *, title: str | None, group: str | None, to_context: bool
) -> ShownOutcome:
    """Write, and turn whatever happened into something to show.

    Every domain failure becomes an outcome rather than a page: the
    text the person typed is still in the box, and replacing the page
    would lose it. `CorpusBusy` is the case that makes this matter -
    a `corpus index` running in a terminal refuses this write, and it
    is worth retrying rather than worth an error page.
    """
    if not text.strip():
        return ShownOutcome(message=words.NOTHING_TO_REMEMBER, role="role-warning")
    try:
        if to_context:
            note, bundle_name = write_context_note(text, title=title, group=group)
            return words.describe_written_to_bundle(note, bundle_name)
        restored: list[OutOfBandChange] = []
        report = write_note(text, title=title, group=group, restored=restored)
        written = words.describe_written(
            report, relative_to_corpus(report.path, existing_corpus().corpus_root)
        )
        return replace(
            written, notes=tuple(describe_change(change) for change in restored)
        )
    except CorpusBusy:
        return ShownOutcome(message=words.CORPUS_BUSY, role="role-warning")
    except KennisError as error:
        return ShownOutcome(
            message=str(error), role="role-error", resolution=error.resolution
        )


@router.get("/remember")
def serve_remember_form(request: Request) -> HTMLResponse:
    return action_page(
        request, "/remember", "forms/remember.html", _remember_context(None)
    )


@router.post("/remember")
def accept_remembered(request: Request, form: PostedForm) -> HTMLResponse:
    """Write a note, and answer with the outcome alone.

    **POST, not GET.** A GET that writes is a GET something will
    follow - a prefetcher, a link checker, a restored history
    entry - and each of those would write a note nobody asked
    for.

    Cross-site protection is the guard's: the token cookie's
    `samesite=strict` keeps it from other sites, and `from_elsewhere`
    refuses a POST from another page on loopback, which the browser
    counts as the same site.
    """
    text_given = str(form.get("text") or "")
    title = str(form.get("title") or "") or None
    group = str(form.get("group") or "") or None
    to_context = str(form.get("target") or "notes") == "context"
    outcome = _remembered(text_given, title=title, group=group, to_context=to_context)
    if not from_htmx(request):
        return action_page(
            request, "/remember", "forms/remember.html", _remember_context(outcome)
        )
    return written(
        TEMPLATES.TemplateResponse(
            request,
            "outcome.html",
            {
                "outcome": outcome,
                # The fields a written note empties are drawn again, and
                # with their hints, which they lost when drawn without them.
                "placeholder": words.REMEMBER_PLACEHOLDER,
                "title_hint": words.TITLE_HINT,
            },
        )
    )
