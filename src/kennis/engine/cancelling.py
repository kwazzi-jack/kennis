"""Stopping a task part way, at the points where it can stop (Brian,
2026-10-27).

**Asked from outside, stopped from inside.** A cancellation is asked of a
task by another thread - a request to the service - and the task stops
itself the next time it reaches a point that can stop, by raising
`TaskCancelled` there. Nothing is interrupted from outside: a thread
cannot be stopped safely where it happens to be, and a write stopped
between two files is the half-done state the staging exists to prevent.

**The points.** Every event a task emits (the service's sink asks after
recording it), a converter's wait (`converters._run_as_group`, which ends
MinerU's process group), the wait for parallel fetches, and `pause`, the
engine's sleep between requests.

**The point of no return.** `publish` and `journalled` call
`past_cancelling` before they place anything. Before it a write has
changed only its mirror, which is discarded when anything raises; after
it the task runs to its end, so a task is never said to be cancelled
after a change it made was kept.

The cancellation is held in a context variable for the thread running the
task. A thread the task starts - a fetch worker - does not see it, and a
request in flight there ends by its own timeout.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from kennis.engine.errors import TaskCancelled


class Cancellation:
    """Whether a task has been asked to stop, and whether it still can."""

    def __init__(self) -> None:
        self._asked = threading.Event()
        self._past = False

    def ask(self) -> None:
        self._asked.set()

    @property
    def asked(self) -> bool:
        return self._asked.is_set()

    @property
    def honoured(self) -> bool:
        """Asked, and not yet past the point where the task can stop."""
        return self._asked.is_set() and not self._past

    def mark_past(self) -> None:
        self._past = True

    def wait(self, seconds: float) -> bool:
        """Wait up to `seconds` for a cancellation that would be honoured."""
        if self._past:
            time.sleep(seconds)
            return False
        return self._asked.wait(seconds) and not self._past


_current: ContextVar[Cancellation | None] = ContextVar(
    "kennis_cancellation", default=None
)


@contextmanager
def cancellable(cancellation: Cancellation) -> Iterator[None]:
    """Run the block as a task `cancellation` can stop."""
    token = _current.set(cancellation)
    try:
        yield
    finally:
        _current.reset(token)


def cancellation_asked() -> bool:
    """Whether the task running on this thread should stop now."""
    cancellation = _current.get()
    return cancellation is not None and cancellation.honoured


def stop_if_asked() -> None:
    """Raise `TaskCancelled` if this thread's task was asked to stop and
    still can."""
    if cancellation_asked():
        raise TaskCancelled()


def past_cancelling() -> None:
    """From here the task runs to its end: what follows places what it
    prepared, and stopping part way through that is what the journal exists
    to repair, not something to ask for."""
    cancellation = _current.get()
    if cancellation is not None:
        cancellation.mark_past()


def pause(seconds: float) -> None:
    """`time.sleep(seconds)`, cut short by a cancellation, which it raises.

    The pauses are a host's own pacing - fifteen seconds between arXiv's
    requests - and a cancelled task should not sit through one first.
    """
    cancellation = _current.get()
    if cancellation is None:
        time.sleep(seconds)
        return
    if cancellation.wait(seconds):
        raise TaskCancelled()


__all__ = [
    "Cancellation",
    "cancellable",
    "cancellation_asked",
    "past_cancelling",
    "pause",
    "stop_if_asked",
]
