"""The windows open on this service, each holding one stream (Brian,
2026-10-30).

**An open window keeps the service.** A window holds `GET /presence`, which
sends nothing until the service stops. The idle timer counts an open request
as work, so the service stays while a window is open and leaves
`service.idle_minutes` after the last one closes - what that setting always
said it did. A window left with nothing behind it was a page whose every
click failed, at an address no later service would answer.

**And it ends when the service stops.** `end` sets every held stream's
event from whichever thread stops the service, and each stream finishes.
Without that, uvicorn would wait for an open response before exiting, and
every stop would wait out the service's join. The window asks once more
when a stream it had ends, and is told no: a stream asked for after the end
is answered with no content, which a browser's EventSource takes as final,
and after that nothing listens at all.

**A window closing ends its stream from the reader's side.** Starlette
ends a streamed response when the server reports the reader gone, under
ASGI spec 2.3, which is what uvicorn reports. `test_service_process.py`
holds it in a real process, because a server that did not would leave a
closed window keeping the service for ever.

**And the service can ask a window to show a passage** (Brian, 2026-11-01).
`kennis open` - and so a clicked `kennis://` link - asks `show`, which sends
a `show` event down the most recently opened stream and waits for the page
to acknowledge it with `POST /shown/<nonce>`. A window that does not answer
within `wait` is not counted as shown, its late acknowledgement is refused,
and the page moves only on an accepted one; so a tab the browser froze and
woke later does not move after a new tab was opened instead. Only the
service builds the path, so a stream carries nothing a client wrote.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Final

# A comment line, which EventSource ignores: the reply's first bytes, so
# the browser sees the stream begin.
OPENED: Final = ": open\n\n"

# How long `show` waits for a window to acknowledge. A page awake in a
# browser answers in milliseconds; past this, a new tab is the better
# answer than a click that seems to do nothing.
SHOW_WAIT_SECONDS: Final = 2.0


@dataclass(eq=False)
class _Stream:
    """One window's stream: the loop it is served on, the event that ends it,
    and the `show` events waiting to be sent down it."""

    loop: asyncio.AbstractEventLoop
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    waiting: asyncio.Queue[str] = field(default_factory=asyncio.Queue)


class Presence:
    """Every stream a window holds, and whether the service has stopped."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        # In the order they opened: the last is the window to ask.
        self._streams: list[_Stream] = []
        self._ended = False
        self._unanswered: dict[str, threading.Event] = {}

    def has_ended(self) -> bool:
        with self._guard:
            return self._ended

    def open_windows(self) -> int:
        with self._guard:
            return len(self._streams)

    def end(self) -> None:
        """Tell every held stream the service is stopping. From any thread."""
        with self._guard:
            self._ended = True
            streams = list(self._streams)
        for stream in streams:
            _set_soon(stream, stream.ended.set)

    def show(self, path: str, *, wait: float = SHOW_WAIT_SECONDS) -> bool:
        """Ask the most recently opened window to show `path`, and say
        whether it acknowledged within `wait` seconds. From any thread but
        a stream's own loop, which this blocks."""
        nonce = secrets.token_hex(8)
        answered = threading.Event()
        with self._guard:
            if self._ended or not self._streams:
                return False
            stream = self._streams[-1]
            self._unanswered[nonce] = answered
        message = json.dumps({"nonce": nonce, "path": path})
        _set_soon(
            stream,
            lambda: stream.waiting.put_nowait(f"event: show\ndata: {message}\n\n"),
        )
        answered.wait(wait)
        # Decided under the guard, as `acknowledge` is, so a page is told yes
        # exactly when this says shown.
        with self._guard:
            del self._unanswered[nonce]
            return answered.is_set()

    def acknowledge(self, nonce: str) -> bool:
        """A page saying it received `show` `nonce`: True while the asker
        still waits, which is the page's leave to move."""
        with self._guard:
            answered = self._unanswered.get(nonce)
            if answered is None:
                return False
            answered.set()
            return True

    async def held(self) -> AsyncIterator[str]:
        """One window's stream: opened, then each `show` sent down it, and
        ended once the service stops."""
        stream = _Stream(asyncio.get_running_loop())
        with self._guard:
            if self._ended:
                stream.ended.set()
            else:
                self._streams.append(stream)
        try:
            yield OPENED
            ending = asyncio.ensure_future(stream.ended.wait())
            try:
                while True:
                    told = asyncio.ensure_future(stream.waiting.get())
                    await asyncio.wait(
                        {ending, told}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if told.done():
                        yield told.result()
                        continue
                    told.cancel()
                    return
            finally:
                ending.cancel()
        finally:
            with self._guard:
                if stream in self._streams:
                    self._streams.remove(stream)


def _set_soon(stream: _Stream, action: Callable[[], None]) -> None:
    try:
        stream.loop.call_soon_threadsafe(action)
    except RuntimeError:
        # The server's loop has already closed, and its streams with it.
        return


__all__ = ["OPENED", "SHOW_WAIT_SECONDS", "Presence"]
