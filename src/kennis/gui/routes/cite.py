"""A passage, with its citation, for the hit card's Copy passage with
citation (#627, Brian 2026-11-06).

The citation is `kennis cite`'s, in the style `literature.citation_style`
names, through `citing.cite`, so the window cannot word it differently from
the command line or an agent. There is no page: Brian asked for no preview,
and copying needs a script, so the entry is drawn only where one can copy.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from kennis.citing import cite, request_for
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError
from kennis.links import target_of
from kennis.render.citations import passage_with_citation

router = APIRouter()


@router.get("/cite/text")
def citation_text(link: str = "") -> PlainTextResponse:
    """The passage `link` names in quotation marks, then its citation; a
    whole document's citation alone."""
    try:
        cited = cite(existing_corpus(), [request_for(target_of(link))])
    except KennisError as error:
        return PlainTextResponse(str(error), status_code=404)
    if cited.refused:
        return PlainTextResponse(cited.refused[0].message, status_code=404)
    (citation,) = cited.citations
    if citation.passage is None:
        return PlainTextResponse(citation.citation)
    return PlainTextResponse(passage_with_citation(citation.passage, citation.citation))


__all__ = ["router"]
