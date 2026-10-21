"""One writer per corpus, and a second one kept waiting until the first lets go.

The lock refused at once until 14e. Every write is now the service's, which
takes the corpus lock only to publish (`kennis/publishing.py`), so a wait is
the length of one publish - or of another kennis process's, which is the
case this file exists for.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kennis.engine.locking import corpus_lock, lock_path

_SETTLE = 0.5
_PATIENCE = 30.0


def test_a_lock_can_be_taken_and_released(tmp_path: Path):
    with corpus_lock(tmp_path):
        pass

    with corpus_lock(tmp_path):
        pass


def test_a_second_holder_waits_and_then_holds(tmp_path: Path):
    """Ordered by two events - the first holder letting go, the second taking
    hold - and checked between them (#63): the waiter must not hold the
    corpus while the first does."""
    holding = threading.Event()
    let_go = threading.Event()
    taken = threading.Event()

    def first() -> None:
        with corpus_lock(tmp_path):
            holding.set()
            let_go.wait(timeout=_PATIENCE)

    def second() -> None:
        with corpus_lock(tmp_path):
            taken.set()

    holder = threading.Thread(target=first, daemon=True)
    holder.start()
    assert holding.wait(timeout=_PATIENCE)
    waiter = threading.Thread(target=second, daemon=True)
    waiter.start()

    assert not taken.wait(timeout=_SETTLE), (
        "the waiter held the corpus beside the holder"
    )
    let_go.set()
    assert taken.wait(timeout=_PATIENCE), "the waiter never took the corpus"
    holder.join(timeout=_PATIENCE)
    waiter.join(timeout=_PATIENCE)


def test_the_lock_is_released_when_the_body_raises(tmp_path: Path):
    """A command that failed must not leave the corpus locked until the next
    reboot."""
    with pytest.raises(ValueError), corpus_lock(tmp_path):
        raise ValueError("something went wrong")

    with corpus_lock(tmp_path):
        pass


def test_a_second_process_waits_for_the_first(tmp_path: Path):
    """The case the lock exists for. A thread-local guard would pass every
    test above and none of this one: the child must not report holding the
    corpus while this process holds it, and must once it lets go."""
    acquired = tmp_path / "acquired"
    program = (
        "from kennis.engine.locking import corpus_lock\n"
        f"with corpus_lock({str(tmp_path)!r}):\n"
        f"    open({str(acquired)!r}, 'w').close()\n"
    )
    with corpus_lock(tmp_path):
        child = subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        time.sleep(2 * _SETTLE)
        held_beside = acquired.exists()
    _, errors = child.communicate(timeout=60)

    assert not held_beside, "the child held the corpus beside this process"
    assert child.returncode == 0, errors.decode("utf-8", "replace")
    assert acquired.exists(), "the child never took the corpus"


def test_the_lock_file_sits_beside_the_corpus(tmp_path: Path):
    assert lock_path(tmp_path).parent == tmp_path


def test_the_lock_file_is_not_a_document(tmp_path: Path):
    """It lives in the corpus directory, which is a git repository, so it
    must be something `.gitignore` can name and nothing mistakes for
    content."""
    assert lock_path(tmp_path).name.startswith(".")
    assert lock_path(tmp_path).suffix == ".lock"


def test_two_corpora_do_not_contend(tmp_path: Path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()

    with corpus_lock(first), corpus_lock(second):
        pass


# ---------------------------------------------------------------------------
# Real processes
# ---------------------------------------------------------------------------


def test_no_two_processes_hold_the_corpus_at_once(tmp_path: Path):
    """A genuine race: eight processes start together and each holds it in
    turn.

    Each writes `in` on acquiring and `out` on releasing, into one journal
    that only the holder writes. Mutual exclusion is the property that no
    `in` follows another `in` without an `out` between them. The eight
    starts are spread over a few milliseconds and each holder sleeps 200ms,
    so a broken lock lets them overlap and the walk below finds it; every
    process must also have held it, since a waiter is never turned away.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    journal = tmp_path / "journal.txt"
    program = (
        "import time\n"
        "from kennis.engine.locking import corpus_lock\n"
        f"journal = {str(journal)!r}\n"
        "def note(what):\n"
        "    with open(journal, 'a') as handle:\n"
        "        handle.write(what + '\\n')\n"
        f"with corpus_lock({str(corpus)!r}):\n"
        "    note('in')\n"
        "    time.sleep(0.2)\n"
        "    note('out')\n"
    )

    running = [
        subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        for _ in range(8)
    ]
    # `communicate` rather than `wait`, because it closes the pipes - an
    # unclosed one is a ResourceWarning and this suite turns warnings into
    # errors.
    failures: list[str] = []
    for process in running:
        _, errors = process.communicate(timeout=120)
        if process.returncode:
            failures.append(errors.decode("utf-8", "replace"))
    assert not failures, failures

    entries = journal.read_text(encoding="utf-8").split()
    assert entries.count("in") == 8, entries
    held = False
    for entry in entries:
        if entry == "in":
            assert not held, f"two processes held the corpus at once: {entries}"
            held = True
        elif entry == "out":
            held = False


def test_a_killed_process_does_not_leave_the_corpus_locked(tmp_path: Path):
    """A crash must not need a manual unlock. The operating system releases
    the file lock when the holder dies, and this asserts kennis relies on
    that rather than on its own cleanup running."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    ready = tmp_path / "ready"
    program = (
        "import time\n"
        "from kennis.engine.locking import corpus_lock\n"
        f"with corpus_lock({str(corpus)!r}):\n"
        f"    open({str(ready)!r}, 'w').close()\n"
        "    time.sleep(60)\n"
    )
    taken = threading.Event()

    def waiting() -> None:
        with corpus_lock(corpus):
            taken.set()

    with subprocess.Popen(
        [sys.executable, "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    ) as holder:
        try:
            for _ in range(600):
                if ready.exists():
                    break
                time.sleep(0.05)
            assert ready.exists(), "the holder never acquired the lock"
            waiter = threading.Thread(target=waiting, daemon=True)
            waiter.start()
            assert not taken.wait(timeout=_SETTLE), "taken while the holder lives"
        finally:
            # Unconditional: the holder sleeps for a minute, so leaving it
            # alive after a failed assertion would hang the suite in
            # `Popen.__exit__`.
            holder.kill()

    # The lock must now be free without anything having cleaned up.
    assert taken.wait(timeout=_PATIENCE), "the corpus stayed locked after the kill"
    waiter.join(timeout=_PATIENCE)


def test_a_wait_is_logged_before_it_begins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """A service waiting at its start answers no client, and each client
    points at the log; found by hand in 14e, when a stray process held the
    corpus and the log said nothing. Asserted while the wait is under way,
    and an uncontended lock logs nothing."""
    holding = threading.Event()
    let_go = threading.Event()

    def holder() -> None:
        with corpus_lock(tmp_path):
            holding.set()
            let_go.wait(timeout=_PATIENCE)

    def taking_and_leaving() -> None:
        with corpus_lock(tmp_path):
            pass

    with caplog.at_level(logging.WARNING, logger="kennis.engine.locking"):
        with corpus_lock(tmp_path):
            pass
        assert caplog.records == []
        first = threading.Thread(target=holder, daemon=True)
        first.start()
        assert holding.wait(timeout=_PATIENCE)
        waiter = threading.Thread(target=taking_and_leaving, daemon=True)
        waiter.start()
        time.sleep(_SETTLE)
        logged_while_waiting = [record.getMessage() for record in caplog.records]
        let_go.set()
        first.join(timeout=_PATIENCE)
        waiter.join(timeout=_PATIENCE)

    assert any("holds the corpus" in message for message in logged_while_waiting)
