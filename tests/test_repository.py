"""Initialising a corpus repository, and recording what each command did.

Git is a requirement rather than an option, so `corpus init` either produces
a working repository or produces nothing at all. Every mutating command that
follows leaves the working tree clean and one commit describing itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import CorpusBusy, CorpusNotFound, GitUnavailable
from kennis.engine.history.git import git
from kennis.engine.history.repository import (
    Repository,
    initialise_corpus,
)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return tmp_path / "corpus"


def log_of(root: Path) -> list[str]:
    return git(["log", "--format=%s"], cwd=root).lines()


# ---------------------------------------------------------------------------
# Initialising
# ---------------------------------------------------------------------------


def test_init_creates_a_repository(corpus: Path):
    initialise_corpus(corpus)

    assert (corpus / ".git").is_dir()
    assert git(["rev-parse", "--is-inside-work-tree"], cwd=corpus).ok


def test_init_creates_the_three_collections(corpus: Path):
    initialise_corpus(corpus)

    assert sorted(path.name for path in corpus.iterdir() if path.is_dir()) == [
        ".git",
        "docs",
        "literature",
        "notes",
    ]


def test_init_marks_the_index_files_binary(corpus: Path):
    """Without this git diffs `embeddings.npy` as text: slow, useless, and
    capable of putting conflict markers inside a numpy array."""
    initialise_corpus(corpus)

    attributes = (corpus / ".gitattributes").read_text(encoding="utf-8")
    assert "*.npy" in attributes
    assert "binary" in attributes


def test_init_writes_a_readme_saying_what_the_corpus_holds(corpus: Path):
    """A directory of converted paper text with no statement of provenance is
    exactly the thing that gets pushed to a public forge by accident."""
    initialise_corpus(corpus)

    readme = (corpus / "README.md").read_text(encoding="utf-8").lower()
    assert "third-party" in readme or "third party" in readme
    assert "remote" in readme


def test_init_commits_its_own_scaffolding(corpus: Path):
    """A repository with no commits makes every later `git diff <commit>` a
    special case; one with a base commit does not."""
    initialise_corpus(corpus)

    assert len(log_of(corpus)) == 1
    assert Repository(corpus).head() is not None


def test_init_leaves_a_clean_working_tree(corpus: Path):
    initialise_corpus(corpus)

    assert Repository(corpus).is_clean()


def test_init_is_refused_rather_than_repeated(corpus: Path):
    """Re-initialising would discard the history it just created."""
    initialise_corpus(corpus)

    with pytest.raises(CorpusBusy) as raised:
        initialise_corpus(corpus)

    assert "already" in str(raised.value)


# ---------------------------------------------------------------------------
# Failing to initialise
# ---------------------------------------------------------------------------


def test_no_git_binary_means_no_partially_initialised_corpus(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """The plan's first test for this milestone. The binary is checked before
    anything is written, so a machine without git is told so and left with
    nothing to clean up."""
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(GitUnavailable):
        initialise_corpus(corpus)

    assert not corpus.exists()


def test_the_refusal_names_how_to_install_git(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(GitUnavailable) as raised:
        initialise_corpus(corpus)

    assert any("install" in note for note in raised.value.__notes__)


# ---------------------------------------------------------------------------
# Opening one
# ---------------------------------------------------------------------------


def test_opening_a_directory_that_is_not_a_corpus_is_refused(tmp_path: Path):
    with pytest.raises(CorpusNotFound):
        Repository(tmp_path / "nowhere").head()


def test_opening_a_directory_that_is_not_a_repository_is_refused(tmp_path: Path):
    (tmp_path / "plain").mkdir()

    with pytest.raises(CorpusNotFound):
        Repository(tmp_path / "plain").head()


# ---------------------------------------------------------------------------
# Recording what a command did
# ---------------------------------------------------------------------------


def test_a_commit_records_the_operation_and_its_counts(corpus: Path):
    """`git log` in a corpus should say what kennis did, not 'update'."""
    initialise_corpus(corpus)
    (corpus / "notes" / "a.md").write_text("# A\n", encoding="utf-8")

    Repository(corpus).commit("add", scope="notes", summary="1 added")

    assert log_of(corpus)[0] == "add(notes): 1 added"


def test_a_commit_leaves_the_working_tree_clean(corpus: Path):
    """The plan's test: every mutating command leaves the working tree
    clean."""
    initialise_corpus(corpus)
    (corpus / "notes" / "a.md").write_text("# A\n", encoding="utf-8")

    Repository(corpus).commit("add", scope="notes", summary="1 added")

    assert Repository(corpus).is_clean()


def test_a_commit_includes_a_deleted_file(corpus: Path):
    initialise_corpus(corpus)
    note = corpus / "notes" / "a.md"
    note.write_text("# A\n", encoding="utf-8")
    Repository(corpus).commit("add", scope="notes", summary="1 added")

    note.unlink()
    Repository(corpus).commit("remove", scope="notes", summary="1 removed")

    assert Repository(corpus).is_clean()
    assert log_of(corpus)[0] == "remove(notes): 1 removed"


def test_committing_nothing_records_nothing_and_is_not_an_error(corpus: Path):
    """Re-adding a document that was already there changes no file. An empty
    commit fills history with noise; a raised error fails a command that
    succeeded."""
    initialise_corpus(corpus)
    before = log_of(corpus)

    recorded = Repository(corpus).commit("add", scope="notes", summary="0 added")

    assert recorded is None
    assert log_of(corpus) == before


def test_each_commit_is_reachable_from_the_next(corpus: Path):
    initialise_corpus(corpus)
    repository = Repository(corpus)
    first = repository.head()

    (corpus / "notes" / "a.md").write_text("# A\n", encoding="utf-8")
    second = repository.commit("add", scope="notes", summary="1 added")

    assert second is not None and second != first
    assert git(["merge-base", "--is-ancestor", str(first), second], cwd=corpus).ok


def test_the_commit_identifies_kennis_rather_than_a_person(corpus: Path):
    """These are machine commits recording what a command did. Attributing
    them to whoever the machine has configured would put a person's name on
    an action they did not take."""
    initialise_corpus(corpus)

    author = git(["log", "-1", "--format=%an <%ae>"], cwd=corpus).stdout.strip()

    assert "kennis" in author


# ---------------------------------------------------------------------------
# Reading the state
# ---------------------------------------------------------------------------


def test_an_untracked_file_makes_the_tree_dirty(corpus: Path):
    initialise_corpus(corpus)
    (corpus / "notes" / "stray.md").write_text("# Stray\n", encoding="utf-8")

    assert not Repository(corpus).is_clean()


def test_an_edited_file_makes_the_tree_dirty(corpus: Path):
    initialise_corpus(corpus)
    (corpus / "README.md").write_text("changed\n", encoding="utf-8")

    assert not Repository(corpus).is_clean()


def test_the_head_commit_is_a_full_identifier(corpus: Path):
    initialise_corpus(corpus)

    head = Repository(corpus).head()

    assert head is not None
    assert len(head) == 40


# ---------------------------------------------------------------------------
# Paths git would rather quote
# ---------------------------------------------------------------------------

# Written as escapes because kennis's own sources are ASCII. The *corpus* is
# not: a literature corpus is full of authors called Mueller and Goncalves
# spelled correctly, and git quotes every one of those paths in its porcelain
# output unless it is asked not to.
UMLAUT_NAME = "notes/M" + chr(0x00FC) + "ller 2020.md"
ARROW_NAME = "notes/a -> b.md"


def a_corpus_with(corpus: Path, name: str, *, committed: bool) -> Repository:
    repository = initialise_corpus(corpus)
    (corpus / name).write_text("body\n", encoding="utf-8")
    if committed:
        repository.commit("add", scope="notes", summary="1 added")
    return repository


def test_an_uncommitted_path_that_is_not_ascii_is_reported_as_itself(corpus: Path):
    """git quotes it as `"notes/M\\303\\274ller 2020.md"`. Reported that way,
    it names no file, so nothing downstream can open, index or restore it."""
    repository = a_corpus_with(corpus, UMLAUT_NAME, committed=False)

    changes = repository.status_names(scope="notes")

    assert changes == [("A", UMLAUT_NAME)]
    assert (corpus / changes[0][1]).is_file()


def test_a_committed_path_that_is_not_ascii_is_reported_as_itself(corpus: Path):
    repository = a_corpus_with(corpus, UMLAUT_NAME, committed=False)
    before = repository.head()
    assert before is not None
    repository.commit("add", scope="notes", summary="1 added")

    changes = repository.diff_names(before, scope="notes")

    assert changes == [("A", UMLAUT_NAME)]


def test_a_path_containing_an_arrow_is_not_read_as_a_rename(corpus: Path):
    """`R  old -> new` is how the non-NUL format joins a rename onto one
    line, so a filename containing those characters was a misparse waiting."""
    repository = a_corpus_with(corpus, ARROW_NAME, committed=False)

    assert repository.status_names(scope="notes") == [("A", ARROW_NAME)]


def test_an_uncommitted_rename_is_read_in_the_right_direction(corpus: Path):
    """The `-z` status format puts the **new** path first and the old second,
    which is the opposite of the `old -> new` it displays. Backwards, this
    reports the surviving file as deleted and the deleted one as present."""
    repository = a_corpus_with(corpus, UMLAUT_NAME, committed=True)
    (corpus / UMLAUT_NAME).rename(corpus / "notes/renamed.md")

    changes = dict(
        (path, status) for status, path in repository.status_names(scope="notes")
    )

    assert changes[UMLAUT_NAME] == "D"
    assert changes["notes/renamed.md"] == "A"


def test_a_committed_rename_is_read_in_the_right_direction(corpus: Path):
    """And `diff --name-status -z` puts them the other way round - status,
    then old, then new - so the two parsers cannot share one order."""
    repository = a_corpus_with(corpus, UMLAUT_NAME, committed=True)
    before = repository.head()
    assert before is not None
    (corpus / UMLAUT_NAME).rename(corpus / "notes/renamed.md")
    repository.commit("move", scope="notes", summary="1 moved")

    changes = dict(
        (path, status) for status, path in repository.diff_names(before, scope="notes")
    )

    assert changes[UMLAUT_NAME] == "D"
    assert changes["notes/renamed.md"] == "A"
