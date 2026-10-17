"""The window's own controls: quitting, the strip and the pane redrawn, the
revision a page checks against, and the palette.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
)
from starlette.background import BackgroundTask

from kennis.context import existing_corpus
from kennis.gui import history, words
from kennis.gui.pages import (
    palette_entries,
    palette_typed,
)
from kennis.gui.pane import pane_now
from kennis.gui.responses import TEMPLATES, action_page, newest_change_said
from kennis.gui.theme import stylesheet
from kennis.holdings import (
    revision,
)

router = APIRouter()


@router.post("/quit")
def quit_interface(request: Request) -> HTMLResponse:
    """Answer, then ask the launcher to stop.

    **Refused while a job runs.** The worker is a daemon thread, and
    ending the process ends it wherever it is - inside the corpus
    lock, or between writing a document and committing it.

    **The stop is a background task**, which Starlette runs only
    once the response has been sent. uvicorn would deliver the page
    either way - its shutdown waits for requests already in flight,
    and an injection that asked first was not caught for that
    reason - so this states the order rather than relying on a
    server's grace. What uvicorn will not do is answer the *next*
    request, so the page carries its stylesheet inline: a `<link>`
    would be fetched from a server that has gone.
    """
    if request.app.state.jobs.running() is not None:
        return TEMPLATES.TemplateResponse(
            request,
            "problem.html",
            {"problem": words.QUIT_WHILE_RUNNING, "resolution": None},
            status_code=409,
        )
    return TEMPLATES.TemplateResponse(
        request,
        "stopped.html",
        {"stopped": words.STOPPED, "stylesheet": stylesheet()},
        background=BackgroundTask(request.app.state.on_quit),
    )


@router.get("/strip/status")
def serve_strip_status(request: Request) -> HTMLResponse:
    """The strip's status line alone, for a finished job (#457)."""
    return TEMPLATES.TemplateResponse(request, "strip-status.html", {})


@router.get("/pane/documents")
def serve_pane_documents(request: Request) -> HTMLResponse:
    """The pane's document count alone, for a finished job (#457)."""
    return TEMPLATES.TemplateResponse(
        request, "pane-documents.html", {"pane": pane_now()}
    )


@router.get("/pane/row/{collection}")
def serve_pane_row(request: Request, collection: str) -> HTMLResponse:
    """One collection's row in the pane, for a finished job (#457)."""
    rows = {row.collection: row for row in pane_now().collections}
    if collection not in rows:
        return HTMLResponse("", status_code=404)
    return TEMPLATES.TemplateResponse(
        request, "pane-row.html", {"row": rows[collection]}
    )


@router.get("/revision")
def serve_revision() -> JSONResponse:
    # Answered on demand, never pushed. One `git rev-parse`, which
    # is cheap enough to ask when a window regains focus and far
    # too expensive to poll. Concern #311.
    context = existing_corpus()
    return JSONResponse(
        {"revision": revision(context), "change": newest_change_said(context)}
    )


@router.get("/palette")
def serve_palette(request: Request) -> HTMLResponse:
    """Every action and place, as one list to type into (11g)."""
    return action_page(
        request,
        "/palette",
        "forms/palette.html",
        {
            "entries": palette_entries()
            + palette_typed(existing_corpus(), history.recent()),
            "palette_prompt": words.PALETTE_PROMPT,
            "palette_empty": words.PALETTE_EMPTY,
            "palette_keys": words.PALETTE_KEYS,
        },
    )
