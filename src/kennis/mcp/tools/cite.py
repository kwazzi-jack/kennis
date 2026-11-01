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

from dataclasses import dataclass
from typing import Final

from kennis.citing import Citation, CiteRefusal
from kennis.citing import CiteRequest as Requested
from kennis.client import api
from kennis.context import existing_corpus

# Enough for every passage one answer cites, few enough to stay readable.
_MAX_REQUESTS: Final = 12

_NOTHING: Final = "no requests"


@dataclass(frozen=True)
class CiteRequest:
    """One passage to cite.

    `document_id` is a search hit's, or `list_corpus`'s. `chunk` is the hit's
    `chunk`; omitted, the document is cited as a whole.
    """

    document_id: str
    chunk: int | None = None


def cite(requests: list[CiteRequest]) -> str:
    """Cite passages from notes, literature or docs.

    Call this for every passage your answer relies on, with the hits'
    `document_id` and `chunk`, all in one call. Each comes back as:

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
    for request in requests:
        if request.chunk is not None and request.chunk < 0:
            return (
                f"{request.document_id}: chunk {request.chunk} is negative. "
                "Pass the `chunk` of a search hit, which counts from 0."
            )
    corpus_root = existing_corpus().corpus_root
    cited = api.cite(
        corpus_root,
        [Requested(request.document_id, request.chunk) for request in requests],
    )
    blocks: dict[int, str] = {}
    for citation in cited.citations:
        blocks[citation.position] = _block(citation)
    for refusal in cited.refused:
        blocks[refusal.position] = _refused(refusal)
    return "\n\n".join(blocks[position] for position in sorted(blocks))


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


__all__ = ["CiteRequest", "cite"]
