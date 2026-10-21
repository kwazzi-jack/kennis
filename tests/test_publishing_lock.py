"""One reader-writer lock per corpus in the process (14e, #507).

A publish holds it exclusively and a read of the collections shared, so a
read sees an operation wholly before or after it, and waits at most for a
publish. The corpus's file lock is taken with the exclusive one and waits
for its holder rather than refusing (e2): the only other holder can be
another kennis process, and waiting for it is what the service does with
every other write.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from kennis.publishing import UpgradeRefused, exclusively, shared

_SETTLE = 0.2


def in_a_thread(work: object) -> threading.Thread:
    assert callable(work)
    started = threading.Thread(target=work, daemon=True)
    started.start()
    return started


def test_a_read_waits_for_a_publish_and_sees_what_it_published(tmp_path: Path):
    """Asserted between the two events it orders (#63): while the publish
    holds the lock the read has not happened, and after it has."""
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def publishing() -> None:
        with exclusively(tmp_path):
            holding.set()
            release.wait(5)
            order.append("published")

    def reading() -> None:
        with shared(tmp_path):
            order.append("read")

    writer = in_a_thread(publishing)
    assert holding.wait(5)
    reader = in_a_thread(reading)
    time.sleep(_SETTLE)
    assert order == []
    release.set()
    writer.join(5)
    reader.join(5)

    assert order == ["published", "read"]


def test_reads_do_not_wait_for_each_other(tmp_path: Path):
    inside = threading.Barrier(2, timeout=5)

    def reading() -> None:
        with shared(tmp_path):
            inside.wait()

    first, second = in_a_thread(reading), in_a_thread(reading)
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()


def test_a_waiting_publish_is_not_starved_by_later_reads(tmp_path: Path):
    order: list[str] = []
    first_read = threading.Event()
    end_first_read = threading.Event()

    def long_read() -> None:
        with shared(tmp_path):
            first_read.set()
            end_first_read.wait(5)
            order.append("first read")

    def publishing() -> None:
        with exclusively(tmp_path):
            order.append("published")

    def later_read() -> None:
        with shared(tmp_path):
            order.append("later read")

    reader = in_a_thread(long_read)
    assert first_read.wait(5)
    writer = in_a_thread(publishing)
    time.sleep(_SETTLE)
    later = in_a_thread(later_read)
    time.sleep(_SETTLE)
    end_first_read.set()
    for thread in (reader, writer, later):
        thread.join(5)

    assert order == ["first read", "published", "later read"]


def test_both_kinds_nest_within_one_thread(tmp_path: Path):
    with exclusively(tmp_path), exclusively(tmp_path), shared(tmp_path):
        pass
    with shared(tmp_path), shared(tmp_path):
        pass


def test_asking_to_publish_while_reading_is_refused_rather_than_deadlocked(
    tmp_path: Path,
):
    """Two readers each asking to upgrade would wait for each other for
    ever; refusing names the mistake at once. Asked on a thread of its own
    and waited for with a bound, so a lock that deadlocks fails here rather
    than hanging the suite."""
    refused: list[bool] = []

    def upgrading() -> None:
        with shared(tmp_path):
            try:
                with exclusively(tmp_path):
                    refused.append(False)
            except UpgradeRefused:
                refused.append(True)

    asking = in_a_thread(upgrading)
    asking.join(5)

    assert not asking.is_alive(), "the upgrade deadlocked"
    assert refused == [True]


def test_two_corpora_do_not_share_a_lock(tmp_path: Path):
    holding = threading.Event()
    release = threading.Event()

    def publishing() -> None:
        with exclusively(tmp_path / "one"):
            holding.set()
            release.wait(5)

    writer = in_a_thread(publishing)
    assert holding.wait(5)
    started = time.monotonic()
    with shared(tmp_path / "two"):
        waited = time.monotonic() - started
    release.set()
    writer.join(5)

    assert waited < _SETTLE
