"""The service leaves when it has had nothing to do for a while (14b).

**One timer, re-armed on activity, never a periodic wake.** An idle service
costs no CPU: nothing runs between one request and the timer firing. This
is not the polling the invariant "on focus, never on a timer" forbids,
which is a page asking the server the same question forever.

**It never fires under work.** When the time is up it asks whether a job is
queued or running or a request is open - a page's event stream is an open
request - and if so arms itself again rather than ending the process under
them. A request that ends re-arms it, so the quiet period is counted from
the last thing that happened.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class IdleTimer:
    """Calls `on_idle` once `seconds` pass with `busy()` false throughout."""

    def __init__(
        self, seconds: float, busy: Callable[[], bool], on_idle: Callable[[], None]
    ) -> None:
        self._seconds = seconds
        self._busy = busy
        self._on_idle = on_idle
        self._guard = threading.Lock()
        self._timer: threading.Timer | None = None
        self._open = 0
        self._stopped = False

    def start(self) -> None:
        self.touch()

    def touch(self) -> None:
        """Something happened: count the quiet period from now."""
        with self._guard:
            if self._stopped:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._seconds, self._expired)
            self._timer.daemon = True
            self._timer.start()

    def request_began(self) -> None:
        with self._guard:
            self._open += 1
        self.touch()

    def request_ended(self) -> None:
        with self._guard:
            self._open -= 1
        self.touch()

    def stop(self) -> None:
        with self._guard:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()

    @property
    def open_requests(self) -> int:
        return self._open

    def _expired(self) -> None:
        with self._guard:
            open_requests = self._open
        if open_requests or self._busy():
            self.touch()
            return
        with self._guard:
            if self._stopped:
                return
            self._stopped = True
        self._on_idle()


__all__ = ["IdleTimer"]
