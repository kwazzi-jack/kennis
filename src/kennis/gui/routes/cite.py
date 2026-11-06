"""A passage's citation in the window (#627): what the hit card's Copy
citation entry fetches, and a page for a reader without a script.

The citation is `kennis cite`'s, in the style `literature.citation_style`
names, through `citing.cite`, so the window cannot word it differently
from the command line or an agent. What is copied is the citation as it
stands in the text; the page shows the reference as well.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from kennis.citing import Citation, cite, request_for
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError
from kennis.gui import words
from kennis.gui.responses import TEMPLATES, problem_page
from kennis.links import target_of

router = APIRouter()


@router.get("/cite")
def serve_citation(request: Request, link: str = "") -> HTMLResponse:
    """The passage `link` names, cited, to select and copy by hand."""
    try:
        citation = _cited(link)
    except KennisError as error:
        return problem_page(request, error)
    return TEMPLATES.TemplateResponse(
        request,
        "cite.html",
        {
            "citation": citation,
            "citation_heading": words.CITATION_HEADING,
            "citation_text": words.CITATION_TEXT,
            "citation_reference": words.CITATION_REFERENCE,
        },
    )


@router.get("/cite/text")
def citation_text(link: str = "") -> PlainTextResponse:
    """The citation alone, for the card's script to put on the clipboard."""
    try:
        return PlainTextResponse(_cited(link).citation)
    except KennisError as error:
        return PlainTextResponse(str(error), status_code=404)


def _cited(link: str) -> Citation:
    cited = cite(existing_corpus(), [request_for(target_of(link))])
    if cited.refused:
        refusal = cited.refused[0]
        raise KennisError(refusal.message, resolution=refusal.resolution)
    return cited.citations[0]


__all__ = ["router"]
