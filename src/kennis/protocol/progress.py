"""What a job's stream says besides the engine's own events (14b).

The service's record of a job, not the engine's: the engine does not know
that a job waits in a lane or that anyone is watching. Here rather than in
`service/`, because a client reads them from the stream.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Elapsed:
    """How long a job has been running, from the stream's own clock.

    The stream's record, not an engine event: the engine does not know
    that anyone is watching, and a clock is about the watching.
    """

    seconds: float


@dataclass(frozen=True, slots=True)
class Queued:
    """The job is waiting for others in its lane, the nearest named.

    The first thing a queued job's history holds, so a watcher who arrives
    while it waits is told why nothing is happening.
    """

    ahead: int
    behind: str


@dataclass(frozen=True, slots=True)
class Began:
    """The job's lane took it, after it had waited. What follows is the
    operation's own events."""


__all__ = ["Began", "Elapsed", "Queued"]
