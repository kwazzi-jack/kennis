"""arXiv's Atom API: the only part of literature that fetches.

Two questions are asked of it. What is this paper, given its identifier - the
answer upgrades a citekey from a title-derived one to a real author-and-year
key. And does arXiv hold a paper with this DOI - many records carry the
published version's, so a DOI is often enough to reach a fetchable preprint.

**Every failure degrades to None rather than raising.** The identifier is
already in hand by the time either call is made, and the identifier is the
part that prevents the same paper landing twice; refusing to add a document
because arXiv was unreachable would trade a small loss for a total one.

A bibcode is never resolved here. That needs the ADS API and a key, which
kennis deliberately does not ask anyone for.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Final

import httpx

from kennis.engine.literature.identifiers import normalize_arxiv_id

_ATOM_API: Final = "https://export.arxiv.org/api/query"
_ATOM_NAMESPACE: Final = {"atom": "http://www.w3.org/2005/Atom"}
_USER_AGENT: Final = "kennis-literature"
_REQUEST_TIMEOUT_SECONDS: Final = 30


@dataclass(frozen=True, slots=True)
class ArxivMetadata:
    """What arXiv says a paper is."""

    title: str
    authors: str
    year: str


def lookup_arxiv_metadata(
    arxiv_id: str, *, client: httpx.Client | None = None
) -> ArxivMetadata | None:
    """Title, authors and year for `arxiv_id`, or None if they cannot be had.

    `client` is supplied by the caller so a test hands over a transport that
    never touches the network; left out, one is built and closed here.
    """
    entry = _entry({"id_list": arxiv_id, "max_results": "1"}, client=client)
    if entry is None:
        return None

    title_element = entry.find("atom:title", _ATOM_NAMESPACE)
    if title_element is None or not title_element.text:
        return None
    published = entry.find("atom:published", _ATOM_NAMESPACE)

    return ArxivMetadata(
        # arXiv wraps a long title across lines in its Atom output.
        title=" ".join(title_element.text.split()),
        authors=" and ".join(_author_names(entry)),
        year=published.text[:4] if published is not None and published.text else "",
    )


def resolve_doi_to_arxiv(doi: str, *, client: httpx.Client | None = None) -> str | None:
    """The arXiv identifier of the preprint behind `doi`, if there is one.

    A miss is not an error: the paper may simply never have been preprinted,
    which the caller reports as needing a document supplied by hand instead.
    """
    entry = _entry({"search_query": f'doi:"{doi}"', "max_results": "1"}, client=client)
    if entry is None:
        return None
    identifier = entry.find("atom:id", _ATOM_NAMESPACE)
    if identifier is None or not identifier.text:
        return None
    return normalize_arxiv_id(identifier.text)


def _entry(
    params: dict[str, str], *, client: httpx.Client | None
) -> ElementTree.Element | None:
    """The first entry of one Atom query, or None for any reason at all."""
    owned = client is None
    active = client or httpx.Client(headers={"User-Agent": _USER_AGENT})
    try:
        response = active.get(
            _ATOM_API, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    finally:
        if owned:
            active.close()

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        return None
    return root.find("atom:entry", _ATOM_NAMESPACE)


def _author_names(entry: ElementTree.Element) -> list[str]:
    names: list[str] = []
    for author in entry.findall("atom:author", _ATOM_NAMESPACE):
        name = author.find("atom:name", _ATOM_NAMESPACE)
        if name is not None and name.text:
            names.append(name.text.strip())
    return names
