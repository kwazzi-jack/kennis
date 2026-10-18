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

from kennis.engine.courtesy import get_politely
from kennis.engine.literature.identifiers import normalize_arxiv_id

_ATOM_API: Final = "https://export.arxiv.org/api/query"
# A paper's own page, which carries its metadata in `citation_*` meta tags.
_ABS_PAGE: Final = "https://arxiv.org/abs/"
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

    The Atom API is asked first. When it fails for any reason, the paper's
    abs page is asked instead (#288): arxiv.org has served it while the API
    refused the same query, which left papers with no authors or year and
    no way to repair them (#283, #287). One extra request, and only on the
    path that has already failed.

    **Both through `courtesy`, so each host's robots.txt decides** (#492).
    On 2026-10-18 `export.arxiv.org` disallowed everything, so the API is
    refused without being asked and the abs page is what answers.
    """
    owned = client is None
    active = client or httpx.Client(headers={"User-Agent": _USER_AGENT})
    try:
        return _from_atom(arxiv_id, active) or _from_abs_page(arxiv_id, active)
    finally:
        if owned:
            active.close()


def _from_atom(arxiv_id: str, client: httpx.Client) -> ArxivMetadata | None:
    entry = _entry({"id_list": arxiv_id, "max_results": "1"}, client=client)
    if entry is None:
        return None
    # The entry must be the paper asked for. arXiv answers a malformed id
    # with HTTP 200 and an entry titled "Error" by "arXiv api core", and that
    # was written as the paper's metadata, with the citekey `coreError`.
    answered = entry.find("atom:id", _ATOM_NAMESPACE)
    if answered is None or normalize_arxiv_id(answered.text or "") != (
        normalize_arxiv_id(arxiv_id) or arxiv_id
    ):
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


def _from_abs_page(arxiv_id: str, client: httpx.Client) -> ArxivMetadata | None:
    """Title, authors and year from the `citation_*` meta tags of the
    paper's abs page, or None.

    The Highwire convention, which Google Scholar indexes, so arXiv keeps
    it. Authors are kept as arXiv writes them there, `Surname, Given`:
    BibTeX reads that form, and a citekey takes the part before the comma.
    """
    from bs4 import BeautifulSoup

    try:
        response = get_politely(
            client,
            f"{_ABS_PAGE}{arxiv_id}",
            user_agent=_USER_AGENT,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    # Anything but a page is not the paper's page, whatever it holds.
    if "html" not in response.headers.get("content-type", ""):
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    def tagged(name: str) -> list[str]:
        return [
            " ".join(str(tag.get("content", "")).split())
            for tag in soup.find_all("meta", attrs={"name": name})
        ]

    # The page must be the paper asked for, as the feed's entry must.
    answered = tagged("citation_arxiv_id")
    if not answered or normalize_arxiv_id(answered[0]) != (
        normalize_arxiv_id(arxiv_id) or arxiv_id
    ):
        return None
    titles = [title for title in tagged("citation_title") if title]
    if not titles:
        return None
    dates = tagged("citation_date")
    return ArxivMetadata(
        title=titles[0],
        authors=" and ".join(name for name in tagged("citation_author") if name),
        year=dates[0][:4] if dates and dates[0][:4].isdigit() else "",
    )


def _entry(
    params: dict[str, str], *, client: httpx.Client | None
) -> ElementTree.Element | None:
    """The first entry of one Atom query, or None for any reason at all."""
    owned = client is None
    active = client or httpx.Client(headers={"User-Agent": _USER_AGENT})
    try:
        response = get_politely(
            active,
            _ATOM_API,
            user_agent=_USER_AGENT,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
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
    entry = root.find("atom:entry", _ATOM_NAMESPACE)
    if entry is None:
        return None
    # An error is reported as an entry: `<id>http://arxiv.org/api/errors#...`.
    identifier = entry.find("atom:id", _ATOM_NAMESPACE)
    if identifier is not None and "/api/errors" in (identifier.text or ""):
        return None
    return entry


def _author_names(entry: ElementTree.Element) -> list[str]:
    names: list[str] = []
    for author in entry.findall("atom:author", _ATOM_NAMESPACE):
        name = author.find("atom:name", _ATOM_NAMESPACE)
        if name is not None and name.text:
            names.append(name.text.strip())
    return names
