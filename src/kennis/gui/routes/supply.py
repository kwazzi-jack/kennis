"""Asking for papers kennis could not fetch (Brian, 2026-10-26).

A sync or an add that ends with papers no open copy exists for names this
dialog in its outcome, and `progress.js` opens it once when the job ends in
front of the reader. Each paper is offered with its page - the person may
be able to download it there, through their institution - and the browser's
own file picker, which sends the file from the reader's computer even when
kennis runs on another (`uploads.py`). Cancel skips every paper; a paper
left without a file is skipped.

One job adds every file chosen. A pack's paper is added as the pack's, as
the sync would have added it; after an add, the person's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse
from starlette.datastructures import UploadFile

from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions, AddOutcome, AddReport
from kennis.engine.corpus.intake import uploaded_as
from kennis.engine.errors import KennisError
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.literature.identifiers import identifier_if_reference
from kennis.engine.refusals import Quoted
from kennis.gui import repairs, words
from kennis.gui.responses import (
    PostedForm,
    action_page,
    refused_a_post,
    refused_in_the_form,
)
from kennis.gui.routes.jobs import started
from kennis.gui.uploads import staged
from kennis.operations import add_documents, supply_a_pack_paper
from kennis.render.refusals import paper_page

router = APIRouter()

# Whose a supplied paper becomes: the pack's after a sync, the person's
# after an add.
_OWNERS: Final = frozenset({"pack", "user"})


@dataclass(frozen=True, slots=True)
class WantedPaper:
    """One paper as the dialog lists it."""

    # `<kind>:<value>`, which is also a pack's address for it.
    reference: str
    kind: str
    value: str
    page: str
    # The kind as a reader knows it: DOI, arXiv, ADS.
    label: str


def _wanted(references: list[str]) -> list[WantedPaper]:
    """The papers the address names, read as a paper's identifier is, so a
    value edited into the address is never taken for one."""
    papers: list[WantedPaper] = []
    for reference in dict.fromkeys(references):
        parsed = identifier_if_reference(reference)
        if parsed is None:
            continue
        papers.append(
            WantedPaper(
                reference=f"{parsed.kind}:{parsed.value}",
                kind=parsed.kind,
                value=parsed.value,
                page=paper_page(parsed.kind, parsed.value),
                label=words.PAPER_KINDS.get(parsed.kind, parsed.kind),
            )
        )
    return papers


@router.get("/supply")
def serve_supply_form(
    request: Request,
    owner: str = "user",
    paper: Annotated[list[str] | None, Query()] = None,
) -> HTMLResponse:
    papers = _wanted(paper or [])
    if owner not in _OWNERS or not papers:
        return refused_a_post(request, words.SUPPLY_NO_PAPERS)
    return action_page(
        request,
        "/supply",
        "forms/supply.html",
        {
            "owner": owner,
            "papers": papers,
            "supply_preamble": words.SUPPLY_PREAMBLE,
            "supply_for_the_pack": words.SUPPLY_FOR_THE_PACK,
            "supply_action": words.SUPPLY_ACTION,
            "choose_the_file": words.CHOOSE_THE_FILE,
            "open_the_paper": repairs.OPEN_THE_PAPER,
        },
    )


@router.post("/supply")
def start_supplying(request: Request, form: PostedForm) -> Response:
    """Add every file chosen, as one job, and skip the papers left empty."""
    owner = str(form.get("owner") or "")
    if owner not in _OWNERS:
        return refused_a_post(request, words.SUPPLY_NO_PAPERS)
    chosen: list[tuple[str, str, Path]] = []
    names: dict[Path, str] = {}
    position = 0
    while (reference := form.get(f"paper-{position}")) is not None:
        part = form.get(f"file-{position}")
        position += 1
        found = _wanted([str(reference)])
        if not found or not isinstance(part, UploadFile) or not part.filename:
            if isinstance(part, UploadFile):
                part.file.close()
            continue
        paper = found[0]
        sent = staged([part])
        chosen.extend((paper.reference, paper.value, path) for path in sent.paths)
        names.update(sent.names)
    if not chosen:
        return refused_in_the_form(
            request, "#supply-problem", words.SUPPLY_NOTHING_CHOSEN
        )

    context = existing_corpus()
    put_back: list[OutOfBandChange] = []

    def supplied(events: EventSink) -> AddReport:
        outcomes: list[AddOutcome] = []
        elapsed = 0.0
        with uploaded_as(names):
            for reference, value, path in chosen:
                try:
                    if owner == "pack":
                        report = supply_a_pack_paper(
                            context, reference, path, events=events, restored=put_back
                        )
                    else:
                        report = add_documents(
                            context,
                            "literature",
                            [str(path)],
                            AddOptions(identifier=value),
                            events=events,
                            restored=put_back,
                        )
                except KennisError as error:
                    # One paper refused is that paper's line, not the end
                    # of the others.
                    outcomes.append(
                        AddOutcome(
                            identifier=reference,
                            outcome=Outcome.FAILED,
                            refusal=Quoted(str(error)),
                        )
                    )
                    continue
                outcomes.extend(report.outcomes)
                elapsed += report.elapsed_seconds
        return AddReport(outcomes=outcomes, elapsed_seconds=elapsed)

    return started(request, "add", supplied, restored=put_back)


__all__ = ["router"]
