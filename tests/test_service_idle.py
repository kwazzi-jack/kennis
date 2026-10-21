"""The service leaves after a quiet period, and never under work (14b).

Shortened by giving the timer a fraction of a second, never by sleeping
thirty minutes: the setting is minutes, the timer is seconds.
"""

from __future__ import annotations

import threading
import time

from kennis.service.idle import IdleTimer

QUIET = 0.2
WAIT = 10.0


def fired_after(timer: IdleTimer, gone: threading.Event) -> float:
    began = time.monotonic()
    timer.start()
    assert gone.wait(WAIT), "the timer never fired"
    return time.monotonic() - began


def test_a_quiet_service_leaves_after_its_time():
    gone = threading.Event()
    timer = IdleTimer(QUIET, lambda: False, gone.set)

    elapsed = fired_after(timer, gone)

    assert elapsed >= QUIET


def test_it_does_not_leave_while_work_is_unfinished():
    gone = threading.Event()
    working = threading.Event()
    working.set()
    timer = IdleTimer(QUIET, working.is_set, gone.set)
    timer.start()

    assert not gone.wait(QUIET * 4), "it left under a job"
    working.clear()
    assert gone.wait(WAIT)


def test_it_does_not_leave_while_a_request_is_open():
    """A page's event stream is an open request for as long as it watches."""
    gone = threading.Event()
    timer = IdleTimer(QUIET, lambda: False, gone.set)
    timer.start()
    timer.request_began()

    assert not gone.wait(QUIET * 4), "it left under an open request"
    timer.request_ended()
    assert gone.wait(WAIT)


# Long beside the interval between touches, because the property is about
# the timer and not about how promptly a loaded runner wakes a sleeper: at
# 0.2 s against touches every 0.1 s, a macOS runner once woke more than
# 0.1 s late and the timer rightly fired (#532).
PATIENT = 2.0
TOUCHED_EVERY = 0.25


def test_activity_counts_the_quiet_period_from_now():
    """Touched at intervals shorter than its time, it stays; the quiet
    period after the last touch is a whole one."""
    gone = threading.Event()
    timer = IdleTimer(PATIENT, lambda: False, gone.set)
    timer.start()
    for _ in range(5):
        threading.Event().wait(TOUCHED_EVERY)
        timer.touch()
        assert not gone.is_set(), "it left between touches"
    last = time.monotonic()

    assert gone.wait(WAIT)
    assert time.monotonic() - last >= PATIENT


def test_a_stopped_timer_never_fires():
    gone = threading.Event()
    timer = IdleTimer(QUIET, lambda: False, gone.set)
    timer.start()
    timer.stop()

    assert not gone.wait(QUIET * 3)


def test_it_fires_once():
    count: list[int] = []
    done = threading.Event()

    def leave() -> None:
        count.append(1)
        done.set()

    timer = IdleTimer(QUIET, lambda: False, leave)
    timer.start()
    assert done.wait(WAIT)
    timer.touch()

    threading.Event().wait(QUIET * 3)
    assert count == [1]
