"""A task asked to stop stops at its next point that can, and keeps nothing
(Brian, 2026-10-27).

The engine's half: the cancellation, where a task checks it, and what a
write leaves behind when it is cancelled. The service's half - the job, the
request and the stream - is `test_service_cancel.py`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine import cancelling
from kennis.engine.cancelling import Cancellation, cancellable
from kennis.engine.corpus import converters
from kennis.engine.corpus.add import AddOptions
from kennis.engine.errors import TaskCancelled
from kennis.engine.events import Event, ItemStarted
from kennis.engine.history.repository import Repository
from kennis.engine.parallel import fetched_in_parallel
from kennis.engine.rag.index import BuildReport
from kennis.operations import add_documents, build_indexes
from kennis.writing import write_note

# Well inside what a test may take, well outside what a prompt stop takes.
_PROMPTLY_SECONDS = 2.0


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def sources(tmp_path: Path, *names: str) -> list[str]:
    folder = tmp_path / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"# {name}\n\nWords about {name}.\n", "utf-8")
    return [str(folder / name) for name in names]


class StopsAt:
    """A sink that asks for the cancellation at its cue - an event of that
    type, the `nth` of them - then asks whether to stop after every event,
    which is what the service's job sink does."""

    def __init__(
        self, cancellation: Cancellation, cue: type[Event], *, nth: int = 1
    ) -> None:
        self._cancellation = cancellation
        self._cue = cue
        self._nth = nth
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)
        if isinstance(event, self._cue):
            self._nth -= 1
            if self._nth == 0:
                self._cancellation.ask()
        cancelling.stop_if_asked()


def tree_of(root: Path) -> dict[str, bytes]:
    """Every file of the three collections, by path."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for collection in ("literature", "docs", "notes")
        for path in sorted((root / collection).rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# The cancellation itself
# ---------------------------------------------------------------------------


def test_nothing_stops_a_task_nobody_asked_to_stop():
    cancellation = Cancellation()
    with cancellable(cancellation):
        cancelling.stop_if_asked()
    cancelling.stop_if_asked()


def test_an_asked_task_stops_at_its_next_point():
    cancellation = Cancellation()
    cancellation.ask()
    with cancellable(cancellation), pytest.raises(TaskCancelled):
        cancelling.stop_if_asked()


def test_a_task_past_cancelling_runs_on():
    cancellation = Cancellation()
    with cancellable(cancellation):
        cancelling.past_cancelling()
        cancellation.ask()
        cancelling.stop_if_asked()


def test_a_pause_is_cut_short_by_a_cancellation():
    """arXiv asks for fifteen seconds between requests; a cancelled task
    must not sit through them."""
    cancellation = Cancellation()
    threading.Timer(0.1, cancellation.ask).start()
    started = time.monotonic()
    with cancellable(cancellation), pytest.raises(TaskCancelled):
        cancelling.pause(30)

    assert time.monotonic() - started < _PROMPTLY_SECONDS


def test_a_pause_past_cancelling_is_waited_in_full():
    """A host's pacing is not skipped because a cancellation came too late
    to be honoured."""
    cancellation = Cancellation()
    cancellation.ask()
    started = time.monotonic()
    with cancellable(cancellation):
        cancelling.past_cancelling()
        cancelling.pause(0.2)

    assert time.monotonic() - started >= 0.15


# ---------------------------------------------------------------------------
# Where a task waits
# ---------------------------------------------------------------------------


def test_a_converter_run_is_ended_when_its_task_is_cancelled():
    """MinerU is twenty seconds a paper and emits nothing while it runs; its
    process group is ended, not waited for."""
    cancellation = Cancellation()
    threading.Timer(0.2, cancellation.ask).start()
    started = time.monotonic()
    with cancellable(cancellation), pytest.raises(TaskCancelled):
        converters._run_as_group(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            timeout=60,
        )

    assert time.monotonic() - started < _PROMPTLY_SECONDS


def test_a_converter_run_finishes_as_before_when_not_cancelled():
    completed = converters._run_as_group(
        [sys.executable, "-c", "print('converted')"], env={}, timeout=60
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "converted"


def test_a_converter_run_still_times_out():
    with pytest.raises(subprocess.TimeoutExpired):
        converters._run_as_group(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            timeout=0.3,
        )


def test_waiting_for_parallel_fetches_stops_when_cancelled():
    released = threading.Event()
    cancellation = Cancellation()
    threading.Timer(0.2, cancellation.ask).start()
    started = time.monotonic()
    try:
        with cancellable(cancellation), pytest.raises(TaskCancelled):
            fetched_in_parallel([1, 2], lambda _: released.wait(10))
    finally:
        released.set()

    assert time.monotonic() - started < _PROMPTLY_SECONDS


# ---------------------------------------------------------------------------
# What a cancelled write leaves
# ---------------------------------------------------------------------------


def test_a_cancelled_add_leaves_the_corpus_as_it_was(isolated: Path):
    context = existing_corpus()
    root = context.corpus_root
    before = (Repository(root).head(), tree_of(root))
    cancellation = Cancellation()
    stops = StopsAt(cancellation, ItemStarted)

    with cancellable(cancellation), pytest.raises(TaskCancelled):
        add_documents(
            context,
            "notes",
            sources(isolated, "oaks.md", "elms.md"),
            AddOptions(),
            events=stops,
        )

    assert (Repository(root).head(), tree_of(root)) == before
    assert Repository(root).is_clean()


def test_a_note_published_is_not_cancelled_by_its_indexing(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """The note is indexed after its publish (#529), and a dense index says
    its progress as events; a cancel there would report as cancelled a note
    that is held. Asked inside the indexing, at a point that would stop."""
    from kennis import writing

    context = existing_corpus()
    cancellation = Cancellation()
    real = writing.index_note

    def asked_while_indexing(*arguments: Any, **keywords: Any) -> Any:
        cancellation.ask()
        cancelling.stop_if_asked()
        return real(*arguments, **keywords)

    monkeypatch.setattr(writing, "index_note", asked_while_indexing)

    with cancellable(cancellation):
        report = write_note(context, "Oaks lose their leaves.")

    assert cancellation.asked
    assert (context.corpus_root / report.path).is_file()


def a_docs_page(corpus: Path) -> None:
    """A docs page as `add_docs` writes one, by hand: a crawl needs a
    network, and this needs only a second collection to index."""
    path = corpus / "docs" / "numpy" / "2.0" / "basics.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nid: docsnumpyba\ntitle: basics\nowner: user\n"
        "id_from: 'docs:numpy/2.0/basics'\n"
        "source:\n  from: 'url:https://numpy.org/doc/2.0/basics'\n"
        "  via: html\n  format: html\n"
        "docs:\n  project: numpy\n  version: '2.0'\n  page: basics\n"
        "---\n\n# basics\n\nArrays of numbers.\n",
        encoding="utf-8",
    )


def test_a_cancelled_index_keeps_only_whole_builds_and_says_which(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """A build is swapped in whole, so one finished before the cancel is a
    correct index of the corpus as it stands: it is committed, and the
    error names it rather than saying nothing changed. Asked once the first
    build returns, because a lexical build emits no event to be asked at."""
    from kennis import operations

    context = existing_corpus()
    root = context.corpus_root
    add_documents(context, "notes", sources(isolated, "oaks.md"), AddOptions())
    a_docs_page(root)
    cancellation = Cancellation()
    real = operations.build_index

    def then_cancelled(*arguments: Any, **keywords: Any) -> BuildReport:
        report = real(*arguments, **keywords)
        cancellation.ask()
        return report

    monkeypatch.setattr(operations, "build_index", then_cancelled)

    with cancellable(cancellation), pytest.raises(TaskCancelled) as cancelled:
        build_indexes(context)

    assert Repository(root).is_clean()
    assert str(cancelled.value) == "the docs index was finished first and was kept"
    assert (root / "index" / "docs" / "latest.json").exists()
    assert not (root / "index" / "notes" / "latest.json").exists()


def test_an_index_cancelled_before_its_first_build_keeps_nothing(isolated: Path):
    context = existing_corpus()
    root = context.corpus_root
    add_documents(context, "notes", sources(isolated, "oaks.md"), AddOptions())
    before = Repository(root).head()
    cancellation = Cancellation()
    cancellation.ask()

    with cancellable(cancellation), pytest.raises(TaskCancelled) as cancelled:
        build_indexes(context)

    assert Repository(root).head() == before
    assert Repository(root).is_clean()
    assert str(cancelled.value) == TaskCancelled.default_message
