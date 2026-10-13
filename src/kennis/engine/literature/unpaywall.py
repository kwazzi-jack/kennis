"""A free, legal copy of a paper known only by its DOI, from Unpaywall.

Asked only when the reader has given an email address for it: Unpaywall
requires one on every request, and kennis does not invent one. A paper
Unpaywall knows no open copy of is a paper the reader supplies themselves.

**Only the paper that was named.** A DOI names the published paper, so only
a published version is fetched. An accepted manuscript may differ from it
and a submitted one is a preprint - kennis once answered a DOI with its
arXiv preprint and stored a different document from the one asked for - so
an accepted manuscript is only *offered*, for the reader to choose, and a
preprint is not mentioned at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

import httpx

from kennis import __version__
from kennis.engine.bounded import get_bounded

_API: Final = "https://api.unpaywall.org/v2/{doi}"
_USER_AGENT: Final = f"kennis/{__version__} (+https://github.com/kwazzi-jack/kennis)"
_REQUEST_TIMEOUT_SECONDS: Final = 30


@dataclass(frozen=True, slots=True)
class OpenCopies:
    """What Unpaywall knows of one DOI that anyone may read."""

    # The published paper, which is what the DOI names. Fetched.
    published: str | None = None
    # The authors' accepted manuscript. Offered, never fetched unasked.
    accepted: str | None = None


def open_copy_of(
    doi: str, *, email: str, client: httpx.Client | None = None
) -> OpenCopies:
    """The PDFs of `doi` anyone may read, by version.

    Empty for every reason there are none - no open copy, only a preprint,
    an unknown DOI, or Unpaywall unreachable - because each leaves the
    reader with the same remedy: their own copy.
    """
    owned = client is None
    active = client or httpx.Client(
        headers={"User-Agent": _USER_AGENT}, follow_redirects=True
    )
    try:
        response = get_bounded(
            active,
            _API.format(doi=quote(doi, safe="/")),
            params={"email": email},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return OpenCopies()
    finally:
        if owned:
            active.close()
    return OpenCopies(
        published=_pdf_of(body, "publishedVersion"),
        accepted=_pdf_of(body, "acceptedVersion"),
    )


def _pdf_of(body: object, version: str) -> str | None:
    """The first PDF of `version` Unpaywall lists, best location first."""
    if not isinstance(body, dict):
        return None
    locations = body.get("oa_locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, dict) or location.get("version") != version:
            continue
        address = location.get("url_for_pdf")
        if isinstance(address, str) and address.startswith(("https://", "http://")):
            return address
    return None


__all__ = ["OpenCopies", "open_copy_of"]
