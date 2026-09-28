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

import queue
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Final

from kennis.engine.errors import KennisError
from kennis.engine.events import Event, EventSink
from kennis.logs import FanOut, LogSink

# How long a finished job stays readable. Long enough to reload the
# page that was watching it, short enough that a day of adds is not
# still in memory at the end of it.
_KEEP_SECONDS: Final = 3600.0

# How long the stream waits on an empty queue before looking again at
# whether the work has finished. Not a poll of anything expensive - it
# is a `queue.get` that wakes to re-check one flag, and without it a
# job that finishes while the queue is empty never closes its stream.
_TICK_SECONDS: Final = 0.25


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
    result: object | None = None
    error: KennisError | None = None
    events: queue.SimpleQueue[Event | None] = field(default_factory=queue.SimpleQueue)
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def failed(self) -> bool:
        return self.error is not None


class _QueueSink:
    """An `EventSink` that puts each event where the stream can find it.

    `SimpleQueue` because it is the one queue whose `put` is
    documented not to block and not to need the GIL released: the
    engine thread must never be slowed by a reader that has gone away.
    """

    def __init__(self, into: queue.SimpleQueue[Event | None]) -> None:
        self._into = into

    def emit(self, event: Event) -> None:
        self._into.put(event)


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
        sink = FanOut(_QueueSink(job.events), LogSink())

        def run() -> None:
            try:
                job.result = work(sink)
            except KennisError as error:
                # Every domain failure becomes the job's answer. A
                # thread that raised would lose it: nothing is waiting
                # on this thread to collect an exception from.
                job.error = error
            finally:
                job.done.set()
                job.events.put(None)

        threading.Thread(target=run, daemon=True, name=f"kennis-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def stream(self, job: Job) -> Iterator[Event]:
        """Every event this job emits, until it ends.

        Ends when the sentinel arrives, and not merely when `done` is
        set: events already on the queue when the work finished must
        still be delivered, or the last item of a batch is the one
        nobody sees.
        """
        while True:
            try:
                event = job.events.get(timeout=_TICK_SECONDS)
            except queue.Empty:
                if job.done.is_set():
                    return
                continue
            if event is None:
                return
            yield event

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


__all__ = ["AlreadyRunning", "Job", "Jobs"]
