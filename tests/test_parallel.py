"""Fetching several things at once, in `engine/parallel.py` (2026-10-27).

Brian asked for requests in parallel wherever a host allows it. What every
caller relies on is here: results come back in the order the items were
given, however they finish; no more than `workers` are in flight; two starts
are `spacing` apart; the caller's callback runs on the caller's thread; and a
fetch's exception reaches the caller.
"""

from __future__ import annotations

import contextlib
import itertools
import threading
import time

import pytest

from kennis.engine.parallel import fetched_in_parallel

# Long enough that a loaded runner reaches the barrier, short enough that a
# serial implementation fails the test quickly rather than hanging it.
PATIENCE_SECONDS = 5.0
# Windows' monotonic clock ticks at about 15.6 ms (#533).
CLOCK_RESOLUTION = 0.016


def test_results_keep_the_order_of_the_items_when_later_ones_finish_first():
    first_may_finish = threading.Event()

    def fetch(item: int) -> int:
        if item == 0:
            assert first_may_finish.wait(PATIENCE_SECONDS)
        else:
            first_may_finish.set()
        return item * 10

    assert fetched_in_parallel([0, 1], fetch, workers=2) == [0, 10]


def test_fetches_overlap_up_to_the_workers():
    """Each fetch waits for the other to be in flight, so a serial run cannot
    pass: the barrier times out and the test fails."""
    together = threading.Barrier(2, timeout=PATIENCE_SECONDS)

    def fetch(item: int) -> int:
        together.wait()
        return item

    assert fetched_in_parallel([1, 2], fetch, workers=2) == [1, 2]


def test_no_more_than_the_workers_are_in_flight():
    lock = threading.Lock()
    in_flight = 0
    most = 0
    two_running = threading.Barrier(2, timeout=PATIENCE_SECONDS)

    def fetch(item: int) -> int:
        nonlocal in_flight, most
        with lock:
            in_flight += 1
            most = max(most, in_flight)
        with contextlib.suppress(threading.BrokenBarrierError):
            two_running.wait()
        with lock:
            in_flight -= 1
        return item

    fetched_in_parallel(list(range(6)), fetch, workers=2)

    assert most == 2


def test_one_worker_is_one_at_a_time():
    lock = threading.Lock()
    in_flight = 0
    most = 0

    def fetch(item: int) -> int:
        nonlocal in_flight, most
        with lock:
            in_flight += 1
            most = max(most, in_flight)
        time.sleep(0.01)
        with lock:
            in_flight -= 1
        return item

    assert fetched_in_parallel(list(range(4)), fetch, workers=1) == [0, 1, 2, 3]
    assert most == 1


def test_two_starts_are_at_least_the_spacing_apart():
    starts: list[float] = []
    lock = threading.Lock()

    def fetch(item: int) -> int:
        with lock:
            starts.append(time.monotonic())
        return item

    spacing = 0.05
    fetched_in_parallel(list(range(4)), fetch, workers=4, spacing=spacing)

    ordered = sorted(starts)
    gaps = [later - earlier for earlier, later in itertools.pairwise(ordered)]
    assert min(gaps) >= spacing - CLOCK_RESOLUTION


def test_the_callback_runs_on_the_calling_thread_once_per_item():
    """A sink is only ever called from the thread that owns it, so no
    `DisplaySink` or log needs a lock."""
    caller = threading.get_ident()
    seen: list[tuple[int, int]] = []

    def fetch(item: int) -> int:
        return item

    fetched_in_parallel(
        [1, 2, 3],
        fetch,
        workers=3,
        on_fetched=lambda item, result: seen.append((threading.get_ident(), item)),
    )

    assert sorted(item for _, item in seen) == [1, 2, 3]
    assert {thread for thread, _ in seen} == {caller}


def test_a_fetch_that_raises_raises_in_the_caller():
    def fetch(item: int) -> int:
        if item == 2:
            raise ValueError("the second one")
        return item

    with pytest.raises(ValueError, match="the second one"):
        fetched_in_parallel([1, 2, 3], fetch, workers=2)


def test_nothing_to_fetch_starts_nothing():
    def fetch(item: int) -> int:
        raise AssertionError("fetched")

    assert fetched_in_parallel([], fetch, workers=4) == []


def test_one_worker_waits_the_spacing_after_each_fetch_ends(
    monkeypatch: pytest.MonkeyPatch,
):
    """A host that names a `Crawl-delay` means the time between requests,
    so with one worker the wait is the whole spacing, before every fetch but
    the first - exactly as the serial loops it replaces slept."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.parallel.time.sleep", lambda seconds: slept.append(seconds)
    )

    fetched_in_parallel([1, 2, 3], lambda item: item, workers=1, spacing=2.0)

    assert slept == [2.0, 2.0]
