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
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Final

# A comment line, which EventSource ignores: the reply's first bytes, so
# the browser sees the stream begin.
OPENED: Final = ": open\n\n"


class Presence:
    """Every stream a window holds, and whether the service has stopped."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._held: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self._ended = False

    def has_ended(self) -> bool:
        with self._guard:
            return self._ended

    def open_windows(self) -> int:
        with self._guard:
            return len(self._held)

    def end(self) -> None:
        """Tell every held stream the service is stopping. From any thread."""
        with self._guard:
            self._ended = True
            held = list(self._held)
        for loop, event in held:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                # The server's loop has already closed, and its streams with it.
                continue

    async def held(self) -> AsyncIterator[str]:
        """One window's stream: opened, and ended once the service stops."""
        event = asyncio.Event()
        entry = (asyncio.get_running_loop(), event)
        with self._guard:
            if self._ended:
                event.set()
            else:
                self._held.add(entry)
        try:
            yield OPENED
            await event.wait()
        finally:
            with self._guard:
                self._held.discard(entry)


__all__ = ["OPENED", "Presence"]
