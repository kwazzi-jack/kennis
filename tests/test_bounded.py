"""A response is read whole, but never without end.

httpx bounds each wait between chunks, not the response, so a server that
trickles keeps a read open as long as it likes. Every request kennis makes
to a host it does not control is read within a size and a time.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from kennis.engine.bounded import TooLarge, TooSlow, get_bounded
from kennis.engine.corpus.intake import convert_url
from kennis.engine.errors import SourceUnreadable

URL = "https://example.org/paper.pdf"


def trickling(chunks: int) -> httpx.Client:
    """A server that keeps sending, a chunk at a time."""

    def body() -> Iterator[bytes]:
        for _ in range(chunks):
            yield b"x"

    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/plain"}, content=body()
            )
        )
    )


def test_a_response_still_arriving_at_its_deadline_is_abandoned():
    """The trickle a sync sat on with nothing on the screen: each wait
    between chunks was short, and the response never ended."""
    with pytest.raises(TooSlow):
        get_bounded(trickling(1000), URL, timeout=30, deadline=0.0)


def test_a_response_within_its_bounds_reads_whole():
    response = get_bounded(trickling(5), URL, timeout=30)

    assert response.content == b"xxxxx"


def test_a_response_past_its_size_is_abandoned():
    with pytest.raises(TooLarge):
        get_bounded(trickling(1000), URL, timeout=30, limit=10)


def test_a_trickling_url_is_refused_as_unreadable_not_waited_on(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("kennis.engine.bounded.MAX_RESPONSE_SECONDS", 0.0)

    with pytest.raises(SourceUnreadable):
        convert_url(URL, client=trickling(1000))


def test_a_clock_that_has_not_moved_still_reaches_a_deadline_of_none(
    monkeypatch: pytest.MonkeyPatch,
):
    """Windows's clock moves in steps of about 15ms, so every chunk of a
    fast response can read the same time as the start; a deadline of none
    is still reached."""
    monkeypatch.setattr("kennis.engine.bounded.time.monotonic", lambda: 100.0)

    with pytest.raises(TooSlow):
        get_bounded(trickling(3), URL, timeout=30, deadline=0.0)
