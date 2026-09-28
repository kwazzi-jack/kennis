"""Two locks, guarding two different things.

Concern #167, and design section 16. `remember` used to take the
corpus-wide lock, so a note written while a terminal was indexing was
refused and **lost**. Section 16 says it should write the note - the
durable part, and per-file atomic - and report that the index was not
rebuilt.

That needs a second lock, one per collection index, so that writing a
document and rebuilding an index can be refused independently. This is
the file that says what must be true of it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import CorpusBusy, IndexBusy
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock, index_lock, index_lock_path
from kennis.engine.rag.index import read_manifest
from kennis.operations import add_documents, build_indexes
from kennis.writing import write_note


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def a_source(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\nAntenna gains drift on long tracks.\n")
    return path


def an_indexed_corpus(tmp_path: Path) -> None:
    """A corpus with a note in it and an index built over it.

    `remember` rebuilds only an index that already exists, so a test
    about deferring that rebuild has to have one to defer.
    """
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(tmp_path, "trees.md"))], AddOptions())
    build_indexes(context, "notes")


class HoldingTheIndex:
    """Another thread holding one collection's index lock.

    A thread rather than a held lock in this thread: `filelock` is
    reentrant per process, so taking the lock here and then calling
    the code under test would succeed and prove nothing. The contention
    has to come from somewhere else.
    """

    def __init__(self, root: Path, collection: str) -> None:
        self._root = root
        self._collection = collection
        self._taken = threading.Event()
        self._release = threading.Event()
        self._thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self) -> None:
        with index_lock(self._root, self._collection):
            self._taken.set()
            self._release.wait(30)

    def __enter__(self) -> HoldingTheIndex:
        self._thread.start()
        assert self._taken.wait(10), "the holding thread never took the lock"
        return self

    def __exit__(self, *_: object) -> None:
        self._release.set()
        self._thread.join(timeout=10)


# ---------------------------------------------------------------------------
# The lock itself
# ---------------------------------------------------------------------------


def test_the_index_lock_lives_beside_the_index_it_guards(isolated: Path):
    """Section 16 names the path: `index/<collection>/.lock`. Beside
    the index rather than at the corpus root, because that is what it
    guards and two collections must not wait on each other."""
    root = index_root(existing_corpus().corpus_root)

    assert index_lock_path(root, "notes") == root / "notes" / ".lock"


def test_a_second_holder_is_refused_rather_than_queued(isolated: Path):
    """Refused, and refused *now*.

    The timing bound is loose on purpose - it is not measuring
    anything, it is separating "told immediately" from "queued behind
    a rebuild that takes minutes", and any number between the two
    does that. Without it the test passes for a lock that waits, and
    waiting is the harm `timeout=0` exists to prevent.
    """
    root = index_root(existing_corpus().corpus_root)

    with HoldingTheIndex(root, "notes"):
        started = time.monotonic()
        with pytest.raises(IndexBusy), index_lock(root, "notes"):
            pass
        waited = time.monotonic() - started

    assert waited < 2.0, waited


def test_one_collections_index_does_not_block_another(isolated: Path):
    """The whole reason it is per collection. A literature build must
    not wait on a notes build that has nothing to do with it."""
    root = index_root(existing_corpus().corpus_root)

    with HoldingTheIndex(root, "notes"), index_lock(root, "literature"):
        pass


def test_the_index_lock_is_not_the_corpus_lock(isolated: Path):
    """Two locks guarding two things. Holding the corpus must not stop
    an index build, and holding an index must not stop a write."""
    context = existing_corpus()
    root = index_root(context.corpus_root)

    with HoldingTheIndex(root, "notes"), corpus_lock(context.corpus_root):
        pass


# ---------------------------------------------------------------------------
# What it buys: a note is never lost
# ---------------------------------------------------------------------------


def test_a_note_is_written_even_while_its_index_is_being_rebuilt(isolated: Path):
    """Concern #167 and design section 16. The note is the durable
    part; the index is derived and can be rebuilt by a later command.
    Refusing the write trades a recoverable gap for a lost note."""
    an_indexed_corpus(isolated)
    root = index_root(existing_corpus().corpus_root)

    with HoldingTheIndex(root, "notes"):
        report = write_note("Solved per scan, not per field.", title="Solver")

    assert report.index_outcome == "deferred"
    assert report.path.is_file()
    assert "Solved per scan" in report.path.read_text(encoding="utf-8")


def test_a_deferred_note_is_committed_like_any_other(isolated: Path):
    """Deferring the *index* must not defer the write. A note that is
    on disk and not in history is one `corpus restore` would undo."""
    an_indexed_corpus(isolated)
    context = existing_corpus()
    root = index_root(context.corpus_root)
    before = Repository(context.corpus_root).head()

    with HoldingTheIndex(root, "notes"):
        write_note("Solved per scan, not per field.", title="Solver")

    assert Repository(context.corpus_root).head() != before


def test_a_note_written_with_no_contention_is_indexed(isolated: Path):
    """The precondition the deferral test depends on. Without this,
    `deferred` could be what happens always and the test above would
    pass for the wrong reason."""
    an_indexed_corpus(isolated)

    report = write_note("Solved per scan, not per field.", title="Solver")

    assert report.index_outcome == "indexed"


def test_a_write_is_still_refused_when_the_corpus_itself_is_busy(isolated: Path):
    """The degradation is about the index, not about the documents.
    Two processes writing documents at once is the thing the corpus
    lock exists to prevent, and this unit does not relax it."""
    context = existing_corpus()

    with corpus_lock(context.corpus_root), pytest.raises(CorpusBusy):
        write_note("Solved per scan, not per field.", title="Solver")


# ---------------------------------------------------------------------------
# The build no longer holds the corpus
# ---------------------------------------------------------------------------


class AsksAnotherThreadForTheCorpus:
    """An `EventSink` that finds out, from elsewhere, whether the
    corpus lock is free at the moment an event is emitted.

    **From another thread**, because `filelock` is reentrant per
    process: asking from the build's own thread would succeed whether
    the build held the corpus or not, and the test would pass without
    testing anything.
    """

    def __init__(self, corpus_root: Path) -> None:
        self._corpus_root = corpus_root
        self.free: list[bool] = []

    def emit(self, event: object) -> None:
        answer: list[bool] = []

        def ask() -> None:
            try:
                with corpus_lock(self._corpus_root):
                    answer.append(True)
            except CorpusBusy:
                answer.append(False)

        asking = threading.Thread(target=ask)
        asking.start()
        asking.join(timeout=10)
        self.free.extend(answer)


def test_a_build_does_not_hold_the_corpus_while_it_runs(isolated: Path):
    """The change that makes the deferral possible, asserted from
    inside the build rather than around it.

    If `build_indexes` kept the corpus lock for its duration, a note
    written during one would still be refused with `CorpusBusy` and
    the index lock would never be reached - so the deferral could
    never happen and the test above would be testing a path no caller
    takes.
    """
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    watcher = AsksAnotherThreadForTheCorpus(context.corpus_root)

    build_indexes(context, "notes", events=watcher)

    assert watcher.free, "the build emitted no event, so nothing was observed"
    assert all(watcher.free), watcher.free


def test_one_busy_index_does_not_abandon_the_others(isolated: Path):
    """Recorded rather than raised: a contended notes index must not
    throw away a literature build that was free, nor lose the commit
    for what did get built."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    # Docs rather than literature: a markdown file with no arXiv id,
    # DOI or bibcode is refused by literature, which would leave that
    # collection empty and skipped for a reason that has nothing to do
    # with this test.
    add_documents(
        context,
        "docs",
        [str(a_source(isolated, "page.md"))],
        AddOptions(project="stimela"),
    )
    root = index_root(context.corpus_root)

    with HoldingTheIndex(root, "notes"):
        result = build_indexes(context)

    assert result.busy == ("notes",)
    assert [index.collection for index in result.built] == ["docs"]


def test_a_build_that_could_not_commit_still_published(isolated: Path):
    """A build costs minutes and a commit costs milliseconds. Failing
    the whole command at the last step would throw away the expensive
    part for the cheap one, so the index is published and history
    waits for the next write."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    taken = threading.Event()
    release = threading.Event()

    def hold_the_corpus() -> None:
        with corpus_lock(context.corpus_root):
            taken.set()
            release.wait(30)

    watcher = HoldsTheCorpusFromTheFirstEvent(hold_the_corpus, taken)
    try:
        result = build_indexes(context, "notes", events=watcher)
    finally:
        release.set()
        watcher.join()

    assert result.committed is False
    assert [index.collection for index in result.built] == ["notes"]
    assert read_manifest(index_root(context.corpus_root), "notes") is not None


class HoldsTheCorpusFromTheFirstEvent:
    """Takes the corpus lock from another thread once a build starts.

    The build releases the corpus before it runs and takes it again to
    commit, so this occupies the gap - which is the only way to reach
    the commit's own contention deterministically.
    """

    def __init__(self, hold: Callable[[], None], taken: threading.Event) -> None:
        self._hold = hold
        self._taken = taken
        self._thread: threading.Thread | None = None

    def emit(self, event: object) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._hold, daemon=True)
        self._thread.start()
        assert self._taken.wait(10)

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=10)


def test_a_busy_index_is_not_reported_as_an_empty_corpus(isolated: Path):
    """Found by running the command, not by the suite.

    A build that reached no collection built zero documents, and the
    command line's `if documents == 0` branch printed "nothing to
    index" at a corpus holding a note. That is a false statement
    rather than an unhelpful one. Concern #331.
    """
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    root = index_root(context.corpus_root)

    with HoldingTheIndex(root, "notes"):
        result = CliRunner().invoke(main, ["corpus", "index", "--collection", "notes"])

    shown = " ".join(result.output.split())
    assert "nothing to index" not in shown
    assert "being rebuilt by another kennis process" in shown


def test_a_staging_directory_is_never_committed(isolated: Path):
    """Releasing the corpus lock during a build means another process
    may commit while one is half-written, and `Repository.commit`
    stages with `git add --all .`. The swap stages at
    `index/<collection>/.<index_id>.staging-XXXX`, a dotfile directory
    git sees like any other."""
    ignored = (existing_corpus().corpus_root / ".gitignore").read_text()

    assert ".staging-" in ignored
    assert ".retiring-" in ignored
