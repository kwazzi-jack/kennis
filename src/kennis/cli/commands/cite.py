"""`kennis cite`: a citation and a link for each passage named (#572).

Takes what a search prints and what a citation carries: `id=X chunk=N` as two
words, a `kennis://` link, or any handle `kennis read` takes, which cites the
whole document. The service formats each in the style
`literature.citation_style` names, as it does for an agent's `cite`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand
from kennis.client import api
from kennis.context import existing_corpus

if TYPE_CHECKING:
    from kennis.citing import CiteRequest

_CHUNK: str = "chunk="


@click.command(cls=KennisCommand, name="cite")
@click.argument("passages", nargs=-1, required=True, metavar="PASSAGE...")
def cite_command(passages: tuple[str, ...]) -> None:
    """Cite passages: each one's citation, its link and its reference.

    A `PASSAGE` is a search hit's `id=X chunk=N` (both words), a
    `kennis://open/...` link, or a handle - an identifier, a title, a
    citekey, a DOI - for the whole document. The citation names the figure,
    table, equation or section the passage is in where the document shows
    one, and the link opens the passage with `kennis open`.
    """
    requests = requests_from(passages)
    cited = api.cite(existing_corpus().corpus_root, requests)
    for citation in cited.citations:
        display.operation("Cited", citation.citation)
        display.detail("+", citation.link)
        # Wrapped with each line carried in, under the link: a reference is
        # long, and one run back to the margin reads as the next citation.
        display.body(citation.reference, indent="    ")
        if citation.alike:
            others = ", ".join(passage_named(position) for position in citation.alike)
            display.note(
                f"reads the same as {others}; the links open different passages"
            )
    for refusal in cited.refused:
        display.failure(f"{refusal.handle}: {refusal.message}")
        if refusal.resolution is not None:
            display.remedy(refusal.resolution)
    if cited.refused:
        raise display.CliError(
            f"{len(cited.refused)} of {len(requests)} passages could not be cited"
        )


def passage_named(position: int) -> str:
    return f"passage {position + 1}"


def requests_from(passages: tuple[str, ...]) -> list[CiteRequest]:
    """The passages as requests, a `chunk=N` joined to the handle before it."""
    from kennis.citing import CiteRequest
    from kennis.links import is_a_link, target_of

    requests: list[CiteRequest] = []
    for passage in passages:
        if passage.startswith(_CHUNK):
            number = passage.removeprefix(_CHUNK)
            if not requests or requests[-1].chunk is not None or not number.isdigit():
                raise display.CliError(
                    f"`{passage}` follows no handle without a chunk; give it after "
                    "the `id=` it belongs to"
                )
            requests[-1] = CiteRequest(requests[-1].handle, int(number))
        elif is_a_link(passage):
            target = target_of(passage)
            requests.append(CiteRequest(target.document_id, target.chunk))
        else:
            requests.append(CiteRequest(passage.removeprefix("id=")))
    return requests


__all__ = ["cite_command"]
