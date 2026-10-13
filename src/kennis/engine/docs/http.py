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

from kennis import __version__

_REQUEST_TIMEOUT_SECONDS: Final = 30

# Who is asking, and where to find out more: a site owner reading their logs
# had a bare name and no way to reach anyone. The product token before the
# slash is also the name robots.txt rules are matched against.
USER_AGENT: Final = (
    f"kennis-docs-fetch/{__version__} (+https://github.com/kwazzi-jack/kennis)"
)

# As many hops as a documentation host plausibly needs: a scheme upgrade,
# a trailing slash and a version alias.
_MAX_REDIRECTS: Final = 5

# The most one response may hold, decoded. A sitemap may be 50 MB by its
# own specification and is the largest thing a documentation site serves on
# purpose; anything over it is a release archive or a video linked from the
# docs, read whole into memory before its content type was ever looked at.
MAX_RESPONSE_BYTES: Final = 50 * 1024 * 1024


class TooLarge(httpx.RequestError):
    """A response longer than `MAX_RESPONSE_BYTES`, abandoned part-way.

    A request error for the same reason as `OffSite`: to every caller it is
    a page that could not be had.
    """


class OffSite(httpx.RequestError):
    """A request, or a redirect, that would leave the site being read.

    An `httpx.HTTPError`, so every caller that already treats a failed
    request as "this page is unavailable" treats this one the same way.
    """


def origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def get_within(
    client: httpx.Client,
    url: str,
    *,
    origin: str,
    limit: int = MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET `url`, following redirects only while they stay on `origin`, and
    reading no more than `limit` bytes of what comes back.

    The response's `url` is where the page actually came from, which is the
    address its relative links are relative to.
    """
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        if urlsplit(target).scheme not in ("http", "https"):
            raise OffSite(f"'{target}' is not an http address")
        if origin_of(target) != origin.lower():
            raise OffSite(f"'{target}' is not on {origin}")
        with client.stream(
            "GET", target, timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=False
        ) as response:
            location = response.headers.get("location")
            if not response.is_redirect or not location:
                return _read_within(response, limit)
            target = urljoin(str(response.url), location)
    raise httpx.TooManyRedirects(f"more than {_MAX_REDIRECTS} redirects from '{url}'")


def _read_within(response: httpx.Response, limit: int) -> httpx.Response:
    """The response, read whole, or `TooLarge` once it passes `limit`.

    Counted as it is decoded, so a small compressed body that inflates
    without end is stopped too, and the declared length is believed only
    when it already says too much. What is returned is a new response over
    the bytes read, without the encoding they no longer have.
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise TooLarge(
            f"'{response.url}' is {declared} bytes, more than {limit}",
            request=response.request,
        )
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise TooLarge(
                f"'{response.url}' is more than {limit} bytes",
                request=response.request,
            )
    headers = [
        (name, value)
        for name, value in response.headers.multi_items()
        if name.lower() not in ("content-encoding", "content-length")
    ]
    return httpx.Response(
        response.status_code,
        headers=headers,
        content=bytes(body),
        request=response.request,
    )


__all__ = [
    "MAX_RESPONSE_BYTES",
    "USER_AGENT",
    "OffSite",
    "TooLarge",
    "get_within",
    "origin_of",
]
