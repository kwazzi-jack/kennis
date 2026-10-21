"""Every write to the collections whole or not at all, to every reader
(14e, #507).

`test_staging.py` holds the mechanism - the mirror, the journal, the
rollback - against a bare repository. This holds the operations a person
runs: a reader arriving between two placements sees neither half, a
restore or a return that fails part way is put back, and a process killed
while publishing is put back by the next service to start.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis import operations
from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine import staging
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.history.repository import Repository
from kennis.engine.staging import journal_path
from kennis.holdings import contents_of
from kennis.protocol.record import find_service, is_held

PATIENCE = 30.0


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path / "corpus"


def sources(tmp_path: Path, *names: str) -> list[str]:
    made: list[str] = []
    for name in names:
        path = tmp_path / "sources" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\nAbout {name}.\n", encoding="utf-8")
        made.append(str(path))
    return made


def titles(context: Context) -> list[str]:
    return sorted(path.stem for path in (context.corpus_root / "notes").rglob("*.md"))


def git_status(corpus: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=corpus,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    ).stdout


class PausesAfterTheFirstPlacement:
    """`make_writable` as publishing calls it, once before each file it
    places, stopping before the second until told to go on - one file
    placed, the moment a reader must not see. Not `os.replace`, which is
    the whole process's and is also how the operation writes in the mirror.
    """

    def __init__(self) -> None:
        self.real = staging.make_writable
        self.placed = 0
        self.paused = threading.Event()
        self.go_on = threading.Event()

    def __call__(self, path: Path) -> None:
        self.placed += 1
        if self.placed == 2:
            self.paused.set()
            self.go_on.wait(PATIENCE)
        self.real(path)


def test_a_reader_between_two_placements_sees_neither_half(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Asserted between the two placements (#63): while the publish is
    paused with one note placed, the read has not returned; once it
    finishes, the read sees both notes."""
    context = existing_corpus()
    pause = PausesAfterTheFirstPlacement()
    monkeypatch.setattr(staging, "make_writable", pause)
    seen: list[int] = []

    writer = threading.Thread(
        target=operations.add_documents,
        args=(context, "notes", sources(tmp_path, "oaks", "elms"), AddOptions()),
        daemon=True,
    )
    writer.start()
    assert pause.paused.wait(PATIENCE), "the publish never placed a file"
    reader = threading.Thread(
        target=lambda: seen.append(len(contents_of(context, "notes").documents)),
        daemon=True,
    )
    reader.start()
    reader.join(0.5)
    read_mid_publish = list(seen)
    pause.go_on.set()
    writer.join(PATIENCE)
    reader.join(PATIENCE)

    assert pause.placed >= 2, "the add placed one file, so there was no between"
    assert read_mid_publish == [], f"a read returned mid-publish: {read_mid_publish}"
    assert seen == [2]


def failing_on_call(number: int) -> Callable[..., None]:
    """`sealed_again`, failing on its `number`th call: the first is the
    hand-deletion restore that runs before every write."""
    real = operations.sealed_again
    calls = [0]

    def sealed(context: Context, paths: list[str]) -> None:
        calls[0] += 1
        if calls[0] == number:
            raise OSError(5, "Input/output error")
        real(context, paths)

    return sealed


def test_a_return_that_fails_part_way_is_put_back(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    context = existing_corpus()
    operations.add_documents(context, "notes", sources(tmp_path, "oaks"), AddOptions())
    point = Repository(corpus).head()
    assert point is not None
    operations.add_documents(context, "notes", sources(tmp_path, "elms"), AddOptions())
    head = Repository(corpus).head()
    monkeypatch.setattr(operations, "sealed_again", failing_on_call(2))

    with pytest.raises(OSError, match="Input/output"):
        operations.return_corpus_to(context, point)

    assert Repository(corpus).head() == head
    assert titles(context) == ["elms", "oaks"]
    assert git_status(corpus) == ""
    assert not journal_path(corpus).exists()


def test_a_restore_that_fails_part_way_is_put_back(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    context = existing_corpus()
    report = operations.add_documents(
        context, "notes", sources(tmp_path, "oaks"), AddOptions()
    )
    identifier = report.outcomes[0].document_id
    assert identifier is not None
    notes = Collection(root=corpus, name="notes")
    operations.remove_a_document(context, notes, notes.resolve(identifier))
    head = Repository(corpus).head()
    monkeypatch.setattr(operations, "sealed_again", failing_on_call(1))

    with pytest.raises(OSError, match="Input/output"):
        operations.restore_a_document(context, identifier, commit="HEAD~1")

    assert Repository(corpus).head() == head
    assert titles(context) == []
    assert git_status(corpus) == ""


# ---------------------------------------------------------------------------
# A real process, killed while publishing


_KILLED_MID_PUBLISH = """
import os, sys, threading
from kennis import operations
from kennis.context import existing_corpus
from kennis.engine import staging
from kennis.engine.corpus.add import AddOptions

real = staging.make_writable
placed = []

def make_writable(path):
    placed.append(path)
    if len(placed) == 2:
        open(sys.argv[1], "w").close()
        threading.Event().wait(600)
    real(path)

staging.make_writable = make_writable
operations.add_documents(existing_corpus(), "notes", sys.argv[2:], AddOptions())
"""


@contextlib.contextmanager
def a_process(arguments: list[str]) -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(
        [sys.executable, "-c", _KILLED_MID_PUBLISH, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=PATIENCE)


@pytest.mark.service
def test_a_publish_killed_part_way_is_put_back_when_the_service_next_starts(
    corpus: Path, tmp_path: Path
):
    """SIGKILL leaves no chance to roll back: the journal and one placed
    note stay, and the next service puts the corpus back before it answers
    anything, and says so to the first client and to no other."""
    head = Repository(corpus).head()
    paused = tmp_path / "paused"
    with a_process([str(paused), *sources(tmp_path, "oaks", "elms")]) as process:
        deadline = time.monotonic() + PATIENCE
        while not paused.exists() and process.poll() is None:
            assert time.monotonic() < deadline, "the publish never placed a file"
            time.sleep(0.05)
        assert paused.exists(), process.stderr.read() if process.stderr else ""
        if sys.platform == "win32":
            process.kill()
        else:
            os.kill(process.pid, signal.SIGKILL)
        process.wait(PATIENCE)
    assert journal_path(corpus).exists()
    assert len(list((corpus / "notes").rglob("*.md"))) == 1

    try:
        first = subprocess.run(
            [str(Path(sys.executable).parent / "kennis"), "corpus", "status"],
            env={**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)},
            capture_output=True,
            text=True,
            timeout=PATIENCE * 2,
            stdin=subprocess.DEVNULL,
        )
        second = subprocess.run(
            [str(Path(sys.executable).parent / "kennis"), "corpus", "status"],
            env={**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)},
            capture_output=True,
            text=True,
            timeout=PATIENCE * 2,
            stdin=subprocess.DEVNULL,
        )

        told = " ".join((first.stdout + first.stderr).split())
        assert first.returncode == 0, told
        assert "stopped part way through an add" in told
        assert "part way" not in second.stdout + second.stderr
        assert not journal_path(corpus).exists()
        assert Repository(corpus).head() == head
        assert not list((corpus / "notes").rglob("*.md"))
        assert git_status(corpus) == ""
    finally:
        record = find_service(corpus)
        if record is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(record.pid, signal.SIGTERM)
            deadline = time.monotonic() + PATIENCE
            while is_held(corpus) and time.monotonic() < deadline:
                time.sleep(0.05)
