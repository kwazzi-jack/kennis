"""Long operations, each in its lane, and their events on the way out.

**Why there is a job at all.** A `corpus add` of one PDF is twenty
seconds of MinerU and a docs crawl is minutes. A request that returns
when the work is done is a page that appears to have hung, and a client
that cannot be told to stop waiting. So the operation runs on a thread
and the request that started it returns at once with somewhere to watch.

**A second write waits its turn** (milestone 14, reversing #422's "one at
a time, said out loud"). Each job names the lane it writes in - `corpus`
for the documents and their history, `index` for a build, `context:` and
a bundle for a project's bundle - and a lane runs its jobs one at a time,
in the order they were asked for, on one worker thread. A job behind
another is `queued`, and its history says so first, so whoever is watching
can say what it is waiting for. Two lanes are what #167 asked for: a note
written during a rebuild is not behind the rebuild.

**The lock is taken by the operation**, inside the call, and only to
publish (14e): an operation prepares in a mirror holding nothing, and a
publish that finds the corpus held waits its turn.
"""

from __future__ import annotations

import logging
import queue
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import Final

from kennis.engine.errors import KennisError
from kennis.engine.events import Event, EventSink
from kennis.engine.history.outofband import OutOfBandChange
from kennis.logs import FanOut, LogSink
from kennis.protocol.progress import Began, Elapsed, Queued

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

# The lanes every corpus has. A bundle's lane is named for the bundle.
CORPUS_LANE: Final = "corpus"
INDEX_LANE: Final = "index"
# The list of known projects, under the state directory (14e).
PROJECTS_LANE: Final = "projects"


def context_lane(bundle: str) -> str:
    """The lane a project's bundle is written in, one per bundle."""
    return f"context:{bundle}"


# What a job's history holds besides the engine's events.
type JobEvent = Event | Queued | Began


@dataclass(slots=True)
class Job:
    """One operation, its events, and whatever it ended as.

    Not frozen, unlike every event: this is the mutable record the
    worker writes its answer into, and the thing an event is a record
    *of*.
    """

    id: str
    kind: str
    lane: str = CORPUS_LANE
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
    # Documents deleted by hand that the operation put back before it ran,
    # filled in place by the operation as `restored=` is everywhere.
    restored: list[OutOfBandChange] = field(default_factory=list)
    # Every event the job has emitted, in order, appended and never
    # taken from: each watcher reads from its own position, so a page
    # drawn mid-job sees what was already reported and two pages watching
    # at once both see everything (#424).
    history: list[JobEvent] = field(default_factory=list)
    changed: threading.Condition = field(default_factory=threading.Condition)
    began: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def failed(self) -> bool:
        return self.error is not None or self.crash is not None

    @property
    def state(self) -> str:
        """`queued`, `running` or `done`, as a watcher would put it."""
        if self.done.is_set():
            return "done"
        return "running" if self.began.is_set() else "queued"

    def record(self, event: JobEvent) -> None:
        with self.changed:
            self.history.append(event)
            self.changed.notify_all()


def _has_news(job: Job, seen: int) -> bool:
    """Whether a watcher that has read `seen` events has more to do."""
    return len(job.history) > seen or job.done.is_set()


class _HistorySink:
    """An `EventSink` that appends each event to the job's history.

    The lock is held for one append and one notify, never while anyone
    waits, so the engine thread is not slowed by a reader that has gone
    away.
    """

    def __init__(self, job: Job) -> None:
        self._job = job

    def emit(self, event: Event) -> None:
        self._job.record(event)


type _Work = tuple[Job, Callable[[EventSink], object]]


class _Lane:
    """One worker thread taking one lane's jobs in the order they came."""

    def __init__(self, name: str, on_finished: Callable[[Job], None]) -> None:
        self.name = name
        self._waiting: queue.Queue[_Work] = queue.Queue()
        self._on_finished = on_finished
        self._worker = threading.Thread(
            target=self._work, daemon=True, name=f"kennis-lane-{name}"
        )
        self._worker.start()

    def submit(self, job: Job, work: Callable[[EventSink], object]) -> None:
        self._waiting.put((job, work))

    def _work(self) -> None:
        while True:
            job, work = self._waiting.get()
            try:
                _run(job, work)
            finally:
                self._on_finished(job)


def _run(job: Job, work: Callable[[EventSink], object]) -> None:
    # A job's clock starts when its lane takes it: time spent waiting is
    # not time the operation took.
    job.started_at = time.monotonic()
    job.started_wall = time.time()
    if job.history:
        job.record(Began())
    job.began.set()
    # Fanned out to the log as well as to the watchers, exactly as the
    # command line does. Without it an operation started from the window
    # left no trace at all, because the only subscriber was a browser
    # that closes its connection when the page is closed. Concern #326.
    sink = FanOut(_HistorySink(job), LogSink())
    try:
        job.result = work(sink)
    except KennisError as error:
        # Every domain failure becomes the job's answer. A thread that
        # raised would lose it: nothing is waiting on this thread to
        # collect an exception from.
        job.error = error
    except Exception as crash:
        # Anything else too, for the same reason. The traceback goes to the
        # log, where a defect report can find it.
        job.crash = crash
        logging.getLogger("kennis.service").exception("the %s job failed", job.kind)
    finally:
        with job.changed:
            job.done.set()
            job.changed.notify_all()


class Jobs:
    """The registry, one per service.

    Held by the application rather than by a module-level variable, so
    a test builds its own and two applications in one process do not
    share a job list.

    `on_change` is told whenever a job is submitted or finishes, which is
    what the idle timer listens to.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lanes: dict[str, _Lane] = {}
        self._guard = threading.Lock()
        self._on_change = on_change

    def start(
        self,
        kind: str,
        work: Callable[[EventSink], object],
        *,
        lane: str = CORPUS_LANE,
        restored: list[OutOfBandChange] | None = None,
    ) -> Job:
        """Queue `work` in `lane` and return the job watching it.

        `work` is handed the sink rather than reaching for one, so what
        it does with events is the caller's decision and this module
        never needs to know which operation it is running.
        """
        with self._guard:
            self._forget_the_old()
            ahead = [
                job
                for job in self._jobs.values()
                if job.lane == lane and not job.done.is_set()
            ]
            job = Job(
                id=secrets.token_urlsafe(8),
                kind=kind,
                lane=lane,
                restored=restored if restored is not None else [],
            )
            if ahead:
                job.history.append(Queued(ahead=len(ahead), behind=ahead[-1].kind))
            self._jobs[job.id] = job
            if lane not in self._lanes:
                self._lanes[lane] = _Lane(lane, self._finished)
            self._lanes[lane].submit(job, work)
        self._changed()
        return job

    def refuse(self, kind: str, error: KennisError) -> Job:
        """Record a task that ended before it began.

        The reader asked for work and it could not start - no context to
        sync, a corpus gone from under the window. That is an outcome of
        their action like any other, so it is a job, worded by the same
        function as a failure mid-way (#475). Nothing runs, and it is in
        no lane, because it is done when it is made.
        """
        job = Job(id=secrets.token_urlsafe(8), kind=kind, lane="", error=error)
        job.began.set()
        job.done.set()
        with self._guard:
            self._forget_the_old()
            self._jobs[job.id] = job
        logging.getLogger("kennis.service").warning(
            "the %s job was refused before it began: %s", kind, error
        )
        return job

    def unfinished(self) -> list[Job]:
        """Every job queued or running, oldest first.

        Asked by Quit and by the idle timer, which must not end the
        process under a job: a worker is a daemon thread and dies wherever
        it is.
        """
        with self._guard:
            return [job for job in self._jobs.values() if not job.done.is_set()]

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def stream(self, job: Job) -> Iterator[JobEvent | Elapsed]:
        """Every event this job records, and its running time, until it ends.

        **From the start, whenever the watcher arrives.** The history is
        read from this watcher's own position, so a page drawn mid-job
        sees what was already reported (#424). It ends once the job is
        done *and* everything in the history has been yielded.

        **The clock rides the wake-up the stream already had**, and says
        nothing while the job waits in its lane: a queued job has not
        started running.
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
            if now >= next_tick and not finished and job.began.is_set():
                yield Elapsed(seconds=now - job.started_at)
                next_tick = now + _ELAPSED_EVERY_SECONDS

    def recent(self) -> list[Job]:
        """The jobs kept, newest first - what the Activity page lists."""
        with self._guard:
            self._forget_the_old()
            # By the order they were started, which the dict keeps, not by
            # `started_at`: Windows' monotonic clock ticks every 16 ms or
            # so, two jobs started within one tick tie, and a stable sort
            # then lists the older one first.
            return list(reversed(self._jobs.values()))

    def _finished(self, job: Job) -> None:
        self._changed()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _forget_the_old(self) -> None:
        cutoff = time.monotonic() - _KEEP_SECONDS
        for job_id, job in list(self._jobs.items()):
            if job.done.is_set() and job.started_at < cutoff:
                del self._jobs[job_id]


__all__ = [
    "CORPUS_LANE",
    "INDEX_LANE",
    "PROJECTS_LANE",
    "Job",
    "JobEvent",
    "Jobs",
    "context_lane",
]
