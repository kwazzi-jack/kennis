"""What is held, and whether the indexes still match it.

Shared by the command line and the graphical interface, so the tests
are about the answer rather than about either front end.

The one that matters most is the `indexed=` argument. `index_freshness`
needs the manifest's document map as well as `built_from`, because
`built_from` is the head *before* the indexing command's own commit -
omit it and `kennis remember` reports the note it has just indexed as
not yet indexed. That was concern #245, found once already, and the
reason this orchestration is shared rather than written twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.holdings import holdings, installed_packs, revision


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated


def a_note(run: CliRunner, tmp_path: Path, name: str, body: str) -> None:
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0


def held(name: str):
    return next(h for h in holdings(existing_corpus()) if h.collection == name)


def test_every_collection_is_reported_even_when_empty(corpus: Path):
    """A collection with nothing in it is a fact, not an absence: a
    person browsing needs to see that `literature` exists and is
    empty, or they conclude kennis has no such thing."""
    reported = holdings(existing_corpus())
    names = [holding.collection for holding in reported]

    # The schema's order, not one invented here and not alphabetical.
    # Asserted against the source of truth rather than a list written
    # beside it, because a list written beside it is a second place to
    # change - which is how this test failed when first written,
    # against an order I had assumed rather than read.
    assert names == list(COLLECTION_NAMES)
    assert all(holding.documents == 0 for holding in reported)


def test_documents_are_counted(corpus: Path, run: CliRunner):
    a_note(run, corpus, "calibration", "Antenna gains.")

    assert held("notes").documents == 1


def test_a_collection_that_was_never_indexed_has_no_freshness(
    corpus: Path, run: CliRunner
):
    """Distinct from an index that has fallen behind. Conflating them
    would tell a fresh corpus its index was stale, which sends someone
    to rebuild an index that does not exist."""
    a_note(run, corpus, "calibration", "Antenna gains.")

    assert held("notes").freshness is None
    assert held("notes").is_current is False


def test_an_index_that_holds_everything_is_current(corpus: Path, run: CliRunner):
    a_note(run, corpus, "calibration", "Antenna gains.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    assert held("notes").freshness is not None
    assert held("notes").is_current is True


def test_a_document_added_after_the_build_is_not_current(corpus: Path, run: CliRunner):
    """`Freshness` deliberately does not call this *stale* - the index
    holds nothing false, only less. But "is there anything to do" is
    what a person browsing is asking, and the answer is yes."""
    a_note(run, corpus, "calibration", "Antenna gains.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    a_note(run, corpus, "imaging", "Deconvolution.")

    assert held("notes").freshness is not None
    assert held("notes").freshness.added == 1
    assert held("notes").is_current is False


def test_remembering_does_not_report_the_note_it_just_indexed_as_missing(
    corpus: Path, run: CliRunner
):
    """Concern #245, as a test on the shared path.

    `built_from` is the head before the indexing command's own commit,
    so without the manifest's document map the diff lists the freshly
    indexed note as added. This is the defect that makes sharing this
    orchestration worth doing.
    """
    a_note(run, corpus, "seed", "Something to index against.")
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    assert run.invoke(main, ["remember", "A decision worth keeping."]).exit_code == 0

    assert held("notes").is_current is True


def test_the_revision_moves_when_the_corpus_is_written_to(corpus: Path, run: CliRunner):
    """What a long-lived view compares against to learn that a
    terminal wrote underneath it. Concern #311."""
    before = revision(existing_corpus())

    a_note(run, corpus, "calibration", "Antenna gains.")

    assert revision(existing_corpus()) != before


def test_a_corpus_with_no_packs_lists_none(corpus: Path):
    assert installed_packs(existing_corpus()) == ()


def test_a_document_that_cannot_be_read_is_counted_separately(
    corpus: Path, run: CliRunner
):
    """A collection reported as holding one when it holds two, one of
    them broken, has been described falsely. `CollectionContents`
    returns the two lists precisely so a caller cannot take the
    documents without seeing there is another half - and a count that
    drops the second half undoes that."""
    a_note(run, corpus, "calibration", "Antenna gains.")
    broken = corpus / "corpus" / "notes" / "broken.md"
    broken.write_text(
        "---\nnot: valid frontmatter for kennis\n---\n\nText.\n", encoding="utf-8"
    )

    assert held("notes").documents == 1
    assert held("notes").unreadable == 1
