"""One writer per corpus, and a second one told so rather than left waiting.

`timeout=0` is the whole design: a command that blocks gives the user a
terminal that has stopped, with nothing said and nothing to press.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kennis.engine.errors import CorpusBusy
from kennis.engine.locking import corpus_lock, lock_path


def test_a_lock_can_be_taken_and_released(tmp_path: Path):
    with corpus_lock(tmp_path):
        pass

    with corpus_lock(tmp_path):
        pass


def test_a_second_holder_is_refused_rather_than_blocked(tmp_path: Path):
    with corpus_lock(tmp_path), pytest.raises(CorpusBusy), corpus_lock(tmp_path):
        pass


def test_the_refusal_names_what_to_do(tmp_path: Path):
    with (
        corpus_lock(tmp_path),
        pytest.raises(CorpusBusy) as raised,
        corpus_lock(tmp_path),
    ):
        pass

    assert raised.value.__notes__


def test_the_lock_is_released_when_the_body_raises(tmp_path: Path):
    """A command that failed must not leave the corpus locked until the next
    reboot."""
    with pytest.raises(ValueError), corpus_lock(tmp_path):
        raise ValueError("something went wrong")

    with corpus_lock(tmp_path):
        pass


def test_a_second_process_is_refused(tmp_path: Path):
    """The case the lock exists for. A thread-local guard would pass every
    test above and none of this one."""
    program = (
        "import sys;"
        "from kennis.engine.locking import corpus_lock;"
        "from kennis.engine.errors import CorpusBusy;"
        f"\ntry:\n    ctx = corpus_lock({str(tmp_path)!r})\n    ctx.__enter__()\n"
        "    print('acquired')\nexcept CorpusBusy:\n    print('busy')\n"
    )
    with corpus_lock(tmp_path):
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )

    assert completed.stdout.strip() == "busy", completed.stderr


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
# Real processes, real commands
# ---------------------------------------------------------------------------
#
# `test_a_second_process_is_refused` above spawns a python snippet and is
# real - injecting a per-process lock file fails it. What it does not cover
# is the case a user actually meets: two `kennis` commands, started at the
# same moment, one of them losing. Concern #109 item 2.


def test_a_real_command_is_refused_while_the_corpus_is_held(tmp_path: Path):
    """The whole path, not the lock alone: the command must exit non-zero
    and say which corpus is busy, rather than block or crash."""
    corpus = tmp_path / "corpus"
    subprocess.run(
        [str(Path(sys.executable).parent / "kennis"), "corpus", "init"],
        env={**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)},
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
        check=True,
    )
    note = tmp_path / "a note.md"
    note.write_text("# A note\n\nBody.\n", encoding="utf-8")

    with corpus_lock(corpus):
        completed = subprocess.run(
            [
                str(Path(sys.executable).parent / "kennis"),
                "corpus",
                "add",
                "-n",
                str(note),
            ],
            env={**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)},
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0, output
    assert "busy" in output.lower() or "another kennis command" in output.lower()
    assert str(corpus) in output


def test_no_two_processes_hold_the_corpus_at_once(tmp_path: Path):
    """A genuine race: eight processes start together and fight for it.

    Each writes `in` on acquiring and `out` on releasing. Mutual exclusion is
    the property that no `in` follows another `in` without an `out` between
    them - which is what a lock is *for*, and which the ordered tests above
    cannot observe because they never contend.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    journal = tmp_path / "journal.txt"
    program = (
        "import os, sys, time\n"
        "from kennis.engine.locking import corpus_lock\n"
        "from kennis.engine.errors import CorpusBusy\n"
        f"journal = {str(journal)!r}\n"
        f"root = {str(corpus)!r}\n"
        "def note(what):\n"
        "    with open(journal, 'a') as handle:\n"
        "        handle.write(what + '\\n')\n"
        "try:\n"
        "    with corpus_lock(root):\n"
        "        note('in')\n"
        "        time.sleep(0.2)\n"
        "        note('out')\n"
        "except CorpusBusy:\n"
        "    note('busy')\n"
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
    # errors. It also makes a child that died before reaching the lock say so,
    # which would otherwise be indistinguishable from one that was refused.
    failures: list[str] = []
    for process in running:
        _, errors = process.communicate(timeout=120)
        if process.returncode:
            failures.append(errors.decode("utf-8", "replace"))
    assert not failures, failures

    entries = journal.read_text(encoding="utf-8").split()
    assert entries, "no process recorded anything"
    assert entries.count("in") + entries.count("busy") == 8
    assert entries.count("in") >= 1, f"nobody got the lock: {entries}"
    # The assertion that discriminates. Measured over ten runs, the journal is
    # always one `in` and seven `busy`: the holder sleeps 200ms and the eight
    # starts are spread over a few, so every other process arrives while it is
    # held. A refusal is therefore proof the processes really did overlap -
    # and it is what a broken lock loses, because then all eight acquire and
    # none is refused. Without it the interleaving loop below passes for free,
    # having only one `in` to look at.
    assert entries.count("busy") >= 1, f"no process ever contended: {entries}"

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

            with pytest.raises(CorpusBusy), corpus_lock(corpus):
                pass
        finally:
            # Unconditional: the holder sleeps for a minute, so leaving it
            # alive after a failed assertion would hang the suite in
            # `Popen.__exit__`.
            holder.kill()

    # The lock must now be free without anything having cleaned up.
    with corpus_lock(corpus):
        pass
