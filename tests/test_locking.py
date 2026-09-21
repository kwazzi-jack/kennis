"""One writer per corpus, and a second one told so rather than left waiting.

`timeout=0` is the whole design: a command that blocks gives the user a
terminal that has stopped, with nothing said and nothing to press.
"""

from __future__ import annotations

import subprocess
import sys
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
