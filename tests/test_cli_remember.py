"""`kennis remember` through the command line.

The plan asks that every command be exercised through the engine in one test
and through the command line in another, and that they agree. The engine half
is `tests/test_remember.py`; these are the properties that only exist once
there is a command - the three routes the text can arrive by, the lock, the
commit, and what a person is told afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path / "corpus"


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated


def only_note(corpus: Path) -> Path:
    found = sorted((corpus / "notes").rglob("*.md"))
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------------------
# The three routes one string arrives by
# ---------------------------------------------------------------------------


def test_text_given_as_an_argument_is_remembered(corpus: Path, run: CliRunner):
    result = run.invoke(main, ["remember", "The pipeline runs on 16 cores."])

    assert result.exit_code == 0, result.output
    assert "The pipeline runs on 16 cores." in only_note(corpus).read_text(
        encoding="utf-8"
    )


def test_text_read_from_a_file_is_remembered(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    path = tmp_path / "jottings.md"
    path.write_text("# Jottings\n\nThe pipeline runs on 16 cores.\n", encoding="utf-8")

    result = run.invoke(main, ["remember", "--from", str(path)])

    assert result.exit_code == 0, result.output
    stored = only_note(corpus).read_text(encoding="utf-8")
    assert "The pipeline runs on 16 cores." in stored
    assert f"path:{path}" in stored


def test_text_piped_in_is_remembered(corpus: Path, run: CliRunner):
    """`echo ... | kennis remember` is how an agent or a shell script writes
    without quoting a paragraph into an argument."""
    result = run.invoke(main, ["remember"], input="The pipeline runs on 16 cores.\n")

    assert result.exit_code == 0, result.output
    assert "The pipeline runs on 16 cores." in only_note(corpus).read_text(
        encoding="utf-8"
    )


def test_two_routes_at_once_are_refused(corpus: Path, run: CliRunner, tmp_path: Path):
    """Not a precedence rule: a caller that supplied both meant one of them,
    and guessing which would silently discard the other."""
    path = tmp_path / "jottings.md"
    path.write_text("Jottings.\n", encoding="utf-8")

    result = run.invoke(main, ["remember", "Some text", "--from", str(path)])

    assert result.exit_code != 0
    assert sorted((corpus / "notes").rglob("*.md")) == []


def test_nothing_to_remember_says_so(corpus: Path, run: CliRunner):
    result = run.invoke(main, ["remember"], input="")

    assert result.exit_code != 0
    assert sorted((corpus / "notes").rglob("*.md")) == []


# ---------------------------------------------------------------------------
# What a command must do that the engine does not
# ---------------------------------------------------------------------------


def test_remember_commits_what_it_wrote(corpus: Path, run: CliRunner):
    before = Repository(corpus).head()

    assert run.invoke(main, ["remember", "A thing worth keeping."]).exit_code == 0

    after = Repository(corpus).head()
    assert after is not None and after != before
    assert Repository(corpus).is_clean()


def test_remembering_the_same_thing_twice_makes_no_second_commit(
    corpus: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "A thing worth keeping."]).exit_code == 0
    first = Repository(corpus).head()

    assert run.invoke(main, ["remember", "A thing worth keeping."]).exit_code == 0

    assert Repository(corpus).head() == first
    assert len(sorted((corpus / "notes").rglob("*.md"))) == 1


def test_remember_is_refused_while_the_corpus_is_busy(corpus: Path, run: CliRunner):
    """A mutating command, so it takes the corpus lock like every other one.
    Design section 16 would rather it wrote the note and deferred only the
    index; that needs a lock per collection, which is not what was built.
    Concern #167."""
    with corpus_lock(corpus):
        result = run.invoke(main, ["remember", "A thing worth keeping."])

    assert result.exit_code != 0
    assert "another kennis command" in result.output.lower()
    assert sorted((corpus / "notes").rglob("*.md")) == []


def test_the_title_can_be_given(corpus: Path, run: CliRunner):
    result = run.invoke(
        main, ["remember", "--title", "Cores", "The pipeline runs on 16 cores."]
    )

    assert result.exit_code == 0, result.output
    assert only_note(corpus).name == "Cores.md"


def test_the_report_says_where_it_went(corpus: Path, run: CliRunner):
    result = run.invoke(main, ["remember", "The pipeline runs on 16 cores."])

    assert "Remembered" in result.output


def test_an_unindexed_corpus_is_told_what_makes_the_note_findable(
    corpus: Path, run: CliRunner
):
    """The note is written either way. What differs is whether searching for
    it now would find it, and saying nothing about that is the failure."""
    result = run.invoke(main, ["remember", "The pipeline runs on 16 cores."])

    assert result.exit_code == 0, result.output
    assert "kennis corpus index" in result.output


def test_a_remembered_note_is_searchable_without_a_second_command(
    corpus: Path, run: CliRunner
):
    """The command-line half of the crossing test."""
    assert run.invoke(main, ["remember", "Old words about calibration."]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    assert (
        run.invoke(
            main,
            ["remember", "Ionospheric screens need direction-dependent solutions."],
        ).exit_code
        == 0
    )

    found = run.invoke(main, ["search", "ionospheric screens", "--mode", "bm25"])
    assert found.exit_code == 0, found.output
    assert "onospheric" in found.output
