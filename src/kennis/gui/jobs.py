"""One long operation at a time, and its events on the way out.

**Why there is a job at all.** A `corpus add` of one PDF is twenty
seconds of MinerU and a docs crawl is minutes. A POST that returns
when the work is done is a browser that appears to have hung, and the
design's own table says a graphical front end "updates widgets as
events arrive". So the operation runs on a thread and the request that
started it returns at once with somewhere to watch.

**One at a time, said out loud.** A second operation would be refused
by the corpus lock anyway, `timeout=0`, so the limit is honest rather
than imposed. What would not be honest is dropping the second click in
silence, so `start` raises `AlreadyRunning`, which names the job
already going and lets the page offer it.

**The lock is taken by the worker.** `filelock` wants the thread that
acquired a lock to be the one that releases it, and `operations.py`
takes it inside the call - so the lock is held for exactly as long as
the work runs and never while the interface is idle.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import Final

from kennis.engine.errors import KennisError
from kennis.engine.events import Event, EventSink
from kennis.logs import FanOut, LogSink

# How long a finished job stays readable. Long enough to reload the
# page that was watching it, short enough that a day of adds is not
# still in memory at the end of it.
_KEEP_SECONDS: Final = 3600.0

# How long a stream waits for a new event before looking at the clock.
# A new event and the job's end both wake it at once, through the
# condition; this bound exists so the elapsed time is said on time.
_TICK_SECONDS: Final = 0.25


# How often a running job's stream says how long it has run. A second,
# because that is the unit the clock shows.
_ELAPSED_EVERY_SECONDS: Final = 1.0


@dataclass(frozen=True, slots=True)
class Elapsed:
    """How long a job has been running, from the stream's own clock.

    The stream's record, not an engine event: the engine does not know
    that a page is watching, and a clock is about the watching.
    """

    seconds: float


class AlreadyRunning(Exception):
    """A second operation was asked for while one was still going."""

    def __init__(self, running: str) -> None:
        super().__init__(running)
        self.running = running


@dataclass(slots=True)
class Job:
    """One operation, its events, and whatever it ended as.

    Not frozen, unlike every event: this is the mutable record the
    worker writes its answer into, and the thing an event is a record
    *of*.
    """

    id: str
    kind: str
    started_at: float = field(default_factory=time.monotonic)
    # Wall-clock time as well, because the Activity page says when, and
    # a monotonic reading is not a time of day.
    started_wall: float = field(default_factory=time.time)
    result: object | None = None
    error: KennisError | None = None
    # Anything else the work raised: a defect, a full disk, a library's own
    # exception. Kept apart from `error` because a `KennisError` carries a
    # sentence and a resolution for the reader and this does not, so a page
    # words it differently - but it is a failure all the same, and an
    # operation that died is never reported as one that finished.
    crash: Exception | None = None
    # Every event the job has emitted, in order, appended and never
    # taken from: each watcher reads from its own position, so a page
    # drawn mid-job sees what was already reported and two pages watching
    # at once both see everything. It was a queue each watcher consumed,
    # which was correct only while one page ever watched (#424).
    history: list[Event] = field(default_factory=list)
    changed: threading.Condition = field(default_factory=threading.Condition)
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def failed(self) -> bool:
        return self.error is not None or self.crash is not None


def _has_news(job: Job, seen: int) -> bool:
    """Whether a watcher that has read `seen` events has more to do."""
    return len(job.history) > seen or job.done.is_set()


class _HistorySink:
    """An `EventSink` that appends each event to the job's history.

    The lock is held for one append and one notify, never while anyone
    waits, so the engine thread is not slowed by a reader that has gone
    away - which was the reason the queue it replaces was chosen.
    """

    def __init__(self, job: Job) -> None:
        self._job = job

    def emit(self, event: Event) -> None:
        with self._job.changed:
            self._job.history.append(event)
            self._job.changed.notify_all()


class Jobs:
    """The registry, one per launch.

    Held by the application rather than by a module-level variable, so
    a test builds its own and two applications in one process do not
    share a job list.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._guard = threading.Lock()

    def start(self, kind: str, work: Callable[[EventSink], object]) -> Job:
        """Run `work` on a thread and return the job watching it.

        `work` is handed the sink rather than reaching for one, so what
        it does with events is the caller's decision and this module
        never needs to know which operation it is running.
        """
        with self._guard:
            self._forget_the_old()
            running = self._running()
            if running is not None:
                raise AlreadyRunning(running.id)
            job = Job(id=secrets.token_urlsafe(8), kind=kind)
            self._jobs[job.id] = job

        # Fanned out to the log as well as to the page, exactly as the
        # command line does. Without it an operation started from the
        # window left no trace at all - not even the item lines section
        # 14 requires - because the only subscriber was a browser that
        # closes its connection when the page is closed. Concern #326.
        sink = FanOut(_HistorySink(job), LogSink())

        def run() -> None:
            try:
                job.result = work(sink)
            except KennisError as error:
                # Every domain failure becomes the job's answer. A
                # thread that raised would lose it: nothing is waiting
                # on this thread to collect an exception from.
                job.error = error
            except Exception as crash:
                # Anything else too, for the same reason: uncaught, it
                # reached the terminal through the thread's excepthook and
                # the page called the job finished. The traceback goes to
                # the log, where a defect report can find it.
                job.crash = crash
                logging.getLogger("kennis.gui").exception("the %s job failed", kind)
            finally:
                with job.changed:
                    job.done.set()
                    job.changed.notify_all()

        threading.Thread(target=run, daemon=True, name=f"kennis-{kind}").start()
        return job

    def running(self) -> Job | None:
        """The job still running, if any.

        Asked by Quit, which must not end the process under a job: the
        worker is a daemon thread and dies wherever it is.
        """
        with self._guard:
            return self._running()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def stream(self, job: Job) -> Iterator[Event | Elapsed]:
        """Every event this job emits, and its running time, until it ends.

        **From the start, whenever the watcher arrives.** The history is
        read from this watcher's own position, so a page drawn mid-job
        sees what was already reported (#424). It ends once the job is
        done *and* everything in the history has been yielded: the last
        item of a batch must still reach the page.

        **The clock rides the wake-up the stream already had.** The wait
        has a short timeout so a finished job is noticed promptly; the
        same wake-up says how long the job has run, once a second.
        Nothing new polls.
        """
        position = 0
        next_tick = time.monotonic() + _ELAPSED_EVERY_SECONDS
        while True:
            with job.changed:
                job.changed.wait_for(
                    partial(_has_news, job, position), timeout=_TICK_SECONDS
                )
                fresh = job.history[position:]
                finished = job.done.is_set()
            position += len(fresh)
            yield from fresh
            if finished and not fresh:
                return
            now = time.monotonic()
            if now >= next_tick and not finished:
                yield Elapsed(seconds=now - job.started_at)
                next_tick = now + _ELAPSED_EVERY_SECONDS

    def recent(self) -> list[Job]:
        """The jobs kept, newest first - what the Activity page lists."""
        with self._guard:
            self._forget_the_old()
            return sorted(self._jobs.values(), key=lambda job: -job.started_at)

    def _running(self) -> Job | None:
        for job in self._jobs.values():
            if not job.done.is_set():
                return job
        return None

    def _forget_the_old(self) -> None:
        cutoff = time.monotonic() - _KEEP_SECONDS
        for job_id, job in list(self._jobs.items()):
            if job.done.is_set() and job.started_at < cutoff:
                del self._jobs[job_id]


__all__ = ["AlreadyRunning", "Elapsed", "Job", "Jobs"]
