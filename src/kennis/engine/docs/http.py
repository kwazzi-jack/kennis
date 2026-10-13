"""Every request a docs add makes, kept on the site it was asked to read.

**Redirects are followed by hand, and only within the origin.** The client
followed any redirect, so a page inside the documentation that redirected to
`http://127.0.0.1:8080/admin` was fetched, filed under the documentation's
address, and its links walked; a sitemap or a Sphinx docname could name any
host at all. The rule is the seed's origin rather than "no private
addresses", because a person may well crawl documentation they serve on
their own machine: what must not happen is a public site sending kennis
there. Only `http` and `https` are ever requested.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

_REQUEST_TIMEOUT_SECONDS: Final = 30

# As many hops as a documentation host plausibly needs: a scheme upgrade,
# a trailing slash and a version alias.
_MAX_REDIRECTS: Final = 5


class OffSite(httpx.RequestError):
    """A request, or a redirect, that would leave the site being read.

    An `httpx.HTTPError`, so every caller that already treats a failed
    request as "this page is unavailable" treats this one the same way.
    """


def origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def get_within(client: httpx.Client, url: str, *, origin: str) -> httpx.Response:
    """GET `url`, following redirects only while they stay on `origin`.

    The response's `url` is where the page actually came from, which is the
    address its relative links are relative to.
    """
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        if urlsplit(target).scheme not in ("http", "https"):
            raise OffSite(f"'{target}' is not an http address")
        if origin_of(target) != origin.lower():
            raise OffSite(f"'{target}' is not on {origin}")
        response = client.get(
            target, timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=False
        )
        location = response.headers.get("location")
        if not response.is_redirect or not location:
            return response
        target = urljoin(str(response.url), location)
    raise httpx.TooManyRedirects(f"more than {_MAX_REDIRECTS} redirects from '{url}'")


__all__ = ["OffSite", "get_within", "origin_of"]
