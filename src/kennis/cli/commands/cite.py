"""`kennis cite`: a citation and a link for each passage named (#572).

Takes what a search prints and what a citation carries: `id=X chunk=N`,
or `path=P chunk=N` as two words, a `kennis://` link, or
any handle `kennis read` takes, which cites the whole document. The service
formats each in the style `literature.citation_style` names, as it does for
an agent's `cite`.
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
_PATH: str = "path="


@click.command(cls=KennisCommand, name="cite")
@click.argument("passages", nargs=-1, required=True, metavar="PASSAGE...")
def cite_command(passages: tuple[str, ...]) -> None:
    """Cite passages: each one's citation, its link and its reference.

    A `PASSAGE` is a search hit's handle and chunk as it prints them (both
    words): `id=X chunk=N` or a project's `path=P chunk=N`; a `kennis://`
    link; or a handle - an identifier, a
    title, a citekey, a DOI - for the whole document. The citation names
    the figure, table, equation or section the passage is in where the
    document shows one, and the link opens the passage with `kennis open`.
    """
    requests = requests_from(passages)
    cited = api.cite(existing_corpus().corpus_root, requests)
    for citation in cited.citations:
        display.operation("Cited", citation.citation)
        display.detail_link("+", citation.link)
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
    """The passages as requests, a `chunk=N` joined to the handle before it.

    A `path=` handle is a context hit's (#623), turned into its project's
    bundle by `client/passages.py`, which the MCP tool shares; the chunk
    joins it before that, so both are one request.
    """
    from pathlib import Path

    from kennis.citing import CiteRequest
    from kennis.client.passages import from_link, from_path
    from kennis.engine.context.bundle import find_bundle
    from kennis.links import is_a_link, target_of

    working = Path.cwd()
    here = find_bundle(working)
    named: list[tuple[str, int | None]] = []
    for passage in passages:
        if passage.startswith(_CHUNK):
            number = passage.removeprefix(_CHUNK)
            if not named or named[-1][1] is not None or not number.isdigit():
                raise display.CliError(
                    f"`{passage}` follows no handle without a chunk; give it after "
                    "the `id=` or `path=` it belongs to"
                )
            named[-1] = (named[-1][0], int(number))
        else:
            named.append((passage, None))
    requests: list[CiteRequest] = []
    for passage, chunk in named:
        if is_a_link(passage):
            if chunk is not None:
                raise display.CliError(
                    f"`{passage}` names its own chunk; drop the `chunk=` after it"
                )
            requests.append(from_link(target_of(passage)))
        elif passage.startswith(_PATH):
            requests.append(
                from_path(
                    passage.removeprefix(_PATH), chunk, here=here, working=working
                )
            )
        else:
            requests.append(CiteRequest(passage.removeprefix("id="), chunk))
    return requests


__all__ = ["cite_command"]
