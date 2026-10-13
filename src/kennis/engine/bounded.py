"""A response read whole, but never without end.

httpx bounds each wait between two chunks, not the response: a server that
sends a byte every few seconds keeps a read open as long as it likes, and a
link to a release archive is read into memory however large it is. Every
request kennis makes to a host it does not control is read through here, so
each has a ceiling on both.
"""

from __future__ import annotations

import time
from typing import Any, Final

import httpx

# The most one response may hold, decoded. A sitemap may be 50 MB by its own
# specification and is the largest thing a documentation site serves on
# purpose; a paper's PDF is a few megabytes. Anything over it is a release
# archive or a video, read whole into memory before its type was looked at.
MAX_RESPONSE_BYTES: Final = 50 * 1024 * 1024

# The longest one response may take, start to finish. Generous, because a
# 50 MB PDF over a slow connection is minutes; the point is that it ends.
MAX_RESPONSE_SECONDS: Final = 300.0


class TooLarge(httpx.RequestError):
    """A response longer than its limit, abandoned part-way.

    A request error, so every caller that already treats a failed request
    as "this could not be had" treats this one the same way.
    """


class TooSlow(httpx.RequestError):
    """A response still arriving at its deadline, abandoned part-way."""


def get_bounded(
    client: httpx.Client,
    url: str,
    *,
    timeout: float,
    params: dict[str, str] | None = None,
    follow_redirects: bool | None = None,
    limit: int | None = None,
    deadline: float | None = None,
) -> httpx.Response:
    """GET `url` as `client.get` would, read within `limit` and `deadline`."""
    options: dict[str, Any] = {"timeout": timeout, "params": params}
    if follow_redirects is not None:
        options["follow_redirects"] = follow_redirects
    with client.stream("GET", url, **options) as response:
        return read_bounded(response, limit=limit, deadline=deadline)


def read_bounded(
    response: httpx.Response,
    *,
    limit: int | None = None,
    deadline: float | None = None,
) -> httpx.Response:
    """A streamed response read whole, or `TooLarge` or `TooSlow`.

    Counted as it is decoded, so a small compressed body that inflates
    without end is stopped too, and the declared length is believed only
    when it already says too much. What is returned is a new response over
    the bytes read, without the encoding they no longer have. A limit left
    out is the module's, read now rather than when this was defined.
    """
    limit = MAX_RESPONSE_BYTES if limit is None else limit
    deadline = MAX_RESPONSE_SECONDS if deadline is None else deadline
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise TooLarge(
            f"'{response.url}' is {declared} bytes, more than {limit}",
            request=response.request,
        )
    started = time.monotonic()
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise TooLarge(
                f"'{response.url}' is more than {limit} bytes",
                request=response.request,
            )
        if time.monotonic() - started > deadline:
            raise TooSlow(
                f"'{response.url}' was still arriving after {deadline:.0f}s",
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
        # Kept so a caller's `raise_for_status` and its redirect history read
        # as they would have from the response itself.
        history=response.history,
    )


__all__ = [
    "MAX_RESPONSE_BYTES",
    "MAX_RESPONSE_SECONDS",
    "TooLarge",
    "TooSlow",
    "get_bounded",
    "read_bounded",
]
