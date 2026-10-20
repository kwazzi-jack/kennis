"""Jobs wait their turn in their lane (14b).

Each ordering test is checked between the two events it orders (#63): the
second job must not have begun while the first runs, and must run once the
first ends.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from kennis.engine.errors import CorpusBusy
from kennis.engine.events import EventSink
from kennis.engine.locking import corpus_lock
from kennis.protocol.progress import Began, Queued
from kennis.service.jobs import (
    CORPUS_LANE,
    INDEX_LANE,
    Jobs,
    context_lane,
)

WAIT = 30.0


def held(
    release: threading.Event, started: threading.Event | None = None
) -> Callable[[EventSink], str]:
    def work(events: EventSink) -> str:
        if started is not None:
            started.set()
        release.wait(WAIT)
        return "held"

    return work


def test_a_second_job_in_a_lane_waits_for_the_first():
    jobs = Jobs()
    release = threading.Event()
    first = jobs.start("add", held(release))
    assert first.began.wait(WAIT)

    second = jobs.start("sync", lambda events: "second")

    assert second.state == "queued"
    assert not second.began.wait(0.3), "the second ran beside the first"
    release.set()
    assert second.done.wait(WAIT)
    assert second.result == "second"


def test_a_queued_job_says_what_it_waits_for_first():
    jobs = Jobs()
    release = threading.Event()
    jobs.start("add", held(release))
    jobs.start("index-of-nothing", lambda events: None)
    third = jobs.start("sync", lambda events: None)
    release.set()
    assert third.done.wait(WAIT)

    assert third.history[0] == Queued(ahead=2, behind="index-of-nothing")
    assert third.history[1] == Began()


def test_jobs_in_a_lane_run_in_the_order_they_were_asked_for():
    jobs = Jobs()
    release = threading.Event()
    order: list[int] = []
    lock = threading.Lock()
    jobs.start("add", held(release))

    def numbered(number: int) -> Callable[[EventSink], None]:
        def work(events: EventSink) -> None:
            with lock:
                order.append(number)

        return work

    started = [jobs.start("add", numbered(number)) for number in range(8)]
    release.set()
    for job in started:
        assert job.done.wait(WAIT)

    assert order == list(range(8))


def test_two_lanes_run_side_by_side():
    jobs = Jobs()
    release = threading.Event()
    jobs.start("index", held(release), lane=INDEX_LANE)

    note = jobs.start("remember", lambda events: "written", lane=CORPUS_LANE)

    assert note.done.wait(WAIT), "a write waited for a build (#167)"
    assert note.history == []
    release.set()


def test_each_bundle_has_its_own_lane():
    assert context_lane("/a/.context") != context_lane("/b/.context")


def test_a_job_with_nothing_ahead_records_no_wait():
    jobs = Jobs()
    job = jobs.start("add", lambda events: None)
    assert job.done.wait(WAIT)

    assert job.history == []


def test_a_job_waits_for_a_corpus_held_elsewhere(tmp_path: Path):
    """A lane's job runs inside `waiting_for_the_corpus`: the corpus held by
    another - a terminal, a build's brief commit - is waited for."""
    jobs = Jobs()
    taken = threading.Event()

    def write(events: EventSink) -> None:
        with corpus_lock(tmp_path):
            taken.set()

    holding = threading.Event()
    let_go = threading.Event()

    def holder() -> None:
        with corpus_lock(tmp_path):
            holding.set()
            let_go.wait(WAIT)

    elsewhere = threading.Thread(target=holder)
    elsewhere.start()
    assert holding.wait(WAIT)
    job = jobs.start("add", write)

    assert not taken.wait(0.3), "the job held the corpus beside its holder"
    let_go.set()
    assert job.done.wait(WAIT)
    assert job.error is None and taken.is_set()
    elsewhere.join(WAIT)


def test_outside_a_job_the_corpus_is_still_refused(tmp_path: Path):
    """The waiting is the job's, not the process's."""
    jobs = Jobs()
    release = threading.Event()
    started = threading.Event()

    def holder(events: EventSink) -> None:
        with corpus_lock(tmp_path):
            started.set()
            release.wait(WAIT)

    jobs.start("add", holder)
    assert started.wait(WAIT)
    try:
        refused = False
        try:
            with corpus_lock(tmp_path):
                pass
        except CorpusBusy:
            refused = True
        assert refused
    finally:
        release.set()


def test_unfinished_lists_queued_and_running_and_tells_its_listener():
    told: list[int] = []
    jobs = Jobs(on_change=lambda: told.append(len(told)))
    release = threading.Event()
    first = jobs.start("add", held(release))
    second = jobs.start("sync", lambda events: None)
    assert first.began.wait(WAIT)

    assert [job.id for job in jobs.unfinished()] == [first.id, second.id]
    release.set()
    assert second.done.wait(WAIT)
    assert jobs.unfinished() == []
    # Two submitted and two finished; the last is told just after the job
    # is marked done, so it is waited for rather than raced.
    deadline = time.monotonic() + WAIT
    while len(told) < 4 and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert len(told) == 4


def test_a_job_s_clock_starts_when_its_lane_takes_it():
    jobs = Jobs()
    release = threading.Event()
    first = jobs.start("add", held(release))
    second = jobs.start("sync", lambda events: None)
    queued_at = second.started_at
    assert first.began.wait(WAIT)
    threading.Event().wait(0.2)
    release.set()
    assert second.done.wait(WAIT)

    assert second.started_at >= queued_at + 0.2
