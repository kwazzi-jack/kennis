"""The `cite` tool: a citation and a link for each passage an agent cites.

An agent that composed its own citation could name a paper kennis does not
hold, or put a locator on a passage that does not carry it; one that
composed its own link could open nothing. So it asks (#572): each passage
comes back as the citation the configured style writes, with the narrowest
locator the chunk offers (#592), the reference, and the `kennis://` link,
and a line of markdown that is the citation as a link.

One block per request, numbered as asked, and a failed request is its own
block, as for the `read_*` tools.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from kennis.citing import Citation, CiteRefusal
from kennis.citing import CiteRequest as Requested
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError

# Enough for every passage one answer cites, few enough to stay readable.
_MAX_REQUESTS: Final = 12

_NOTHING: Final = "no requests"


@dataclass(frozen=True)
class CiteRequest:
    """One passage to cite, named by exactly one of two handles.

    `document_id` for a hit from notes, literature or docs (or from
    `list_corpus`); `path` for a project's context hit, as its `path=`
    gives it. `chunk` is the hit's `chunk`; omitted, the document is cited whole.
    """

    document_id: str | None = None
    chunk: int | None = None
    path: str | None = None


def cite(requests: list[CiteRequest]) -> str:
    """Cite passages from notes, literature, docs or a project's context.

    Call this for every passage your answer relies on, all in one call:
    a hit's `document_id`, or a context hit's `path`, with its `chunk`.
    Each comes back as:

    - `markdown`: the citation as a link to the passage. Write it as given.
    - `link`: the `kennis://` link alone. Write it after the citation where a
      link cannot be shown.
    - `locator`: the figure, table, equation or section the passage is in,
      if any, to name in your own words ("in section 2.1 of ...").
    - `reference`: the entry for a list of references.

    Never write a citation or a `kennis://` link yourself. A note saying a
    citation reads the same as another means their links open different
    passages: say what each one is.
    """
    if not requests:
        return _NOTHING
    if len(requests) > _MAX_REQUESTS:
        return (
            f"{len(requests)} requests is more than one call cites. "
            f"Ask for at most {_MAX_REQUESTS}."
        )
    for position, request in enumerate(requests, start=1):
        handles = [request.document_id, request.path]
        if sum(handle is not None for handle in handles) != 1:
            return (
                f"[{position}] names {sum(h is not None for h in handles)} handles. "
                "Give exactly one of `document_id` or `path`."
            )
        if request.chunk is not None and request.chunk < 0:
            return (
                f"[{position}] chunk {request.chunk} is negative. "
                "Pass the `chunk` of a search hit, which counts from 0."
            )
    # A request this server cannot turn into one the service takes is
    # refused at its own position, as the service refuses one it cannot
    # cite: one bad path must not cost the batch.
    blocks: dict[int, str] = {}
    sent: list[int] = []
    asked: list[Requested] = []
    for position, request in enumerate(requests):
        try:
            asked.append(requested(request))
        except KennisError as error:
            blocks[position] = _refused(
                CiteRefusal(
                    position=position,
                    handle=_handle_of(request),
                    message=str(error),
                    resolution=error.resolution,
                )
            )
            continue
        sent.append(position)
    if asked:
        cited = api.cite(existing_corpus().corpus_root, asked)
        for citation in cited.citations:
            position = sent[citation.position]
            alike = [sent[other] for other in citation.alike]
            blocks[position] = _block(replace(citation, position=position, alike=alike))
        for refusal in cited.refused:
            position = sent[refusal.position]
            blocks[position] = _refused(replace(refusal, position=position))
    return "\n\n".join(blocks[position] for position in sorted(blocks))


def _handle_of(request: CiteRequest) -> str:
    return request.document_id or request.path or ""


def requested(request: CiteRequest) -> Requested:
    """The request the service takes, a context hit's bundle found from
    where this server runs, as `kennis cite` finds it (#623)."""
    from pathlib import Path

    from kennis.client.passages import from_path
    from kennis.engine.context.bundle import find_bundle

    if request.path is not None:
        working = Path.cwd()
        return from_path(
            request.path, request.chunk, here=find_bundle(working), working=working
        )
    return Requested(request.document_id or "", request.chunk)


def _block(citation: Citation) -> str:
    lines = [
        f"[{citation.position + 1}] {citation.citation}",
        f"markdown: {citation.markdown}",
        f"link: {citation.link}",
    ]
    if citation.locator is not None:
        lines.append(f"locator: {citation.locator.kind} {citation.locator.value}")
    lines.append(f"reference: {citation.reference}")
    if citation.alike:
        others = ", ".join(f"[{position + 1}]" for position in citation.alike)
        lines.append(
            f"note: reads the same as {others}; the links open different passages"
        )
    return "\n".join(lines)


def _refused(refusal: CiteRefusal) -> str:
    resolution = f" Run `{refusal.resolution}`." if refusal.resolution else ""
    return f"[{refusal.position + 1}] {refusal.handle}: {refusal.message}.{resolution}"


__all__ = ["CiteRequest", "cite", "requested"]
