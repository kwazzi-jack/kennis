"""Removing a document, putting one back, and returning the corpus to a
point in its history - one sequence each, in `operations.py`, for every
front end (Brian, 2026-10-18).

A point is a commit `corpus history` lists. A return makes the three
collections exactly as they were there, records whatever was not yet
recorded first so nothing is lost, leaves the index as built, and is itself
a commit - so it is undone by returning to the point before it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import Context, existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import DocumentNotFound, InputError
from kennis.engine.history.history import (
    read_history,
    removed_in,
    what_a_return_changes,
)
from kennis.engine.history.repository import Repository
from kennis.operations import (
    remove_a_document,
    restore_a_document,
    return_corpus_to,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    ).stdout


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    runner = CliRunner()
    assert runner.invoke(main, ["corpus", "init"]).exit_code == 0
    return runner


def added(run: CliRunner, tmp_path: Path, name: str, text: str) -> None:
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    result = run.invoke(main, ["corpus", "add", "-n", str(source)])
    assert result.exit_code == 0, result.output


def titles(context: Context, collection: str = "notes") -> list[str]:
    held = Collection(root=context.corpus_root, name=collection).contents()
    return sorted(document.frontmatter.title for document in held.documents)


def note(context: Context, title: str) -> Path:
    held = Collection(root=context.corpus_root, name="notes").contents()
    (found,) = [one for one in held.documents if one.frontmatter.title == title]
    return found.md_path


def head(context: Context) -> str:
    commit = Repository(context.corpus_root).head()
    assert commit is not None
    return commit


@pytest.fixture
def corpus(run: CliRunner, tmp_path: Path) -> tuple[Context, str]:
    """`kept` and `changed` held, and the commit they were held at; then
    `later` added, `changed` edited and `kept` removed after it."""
    added(run, tmp_path, "kept", "# Kept\n\nThe first note.\n")
    added(run, tmp_path, "changed", "# Changed\n\nAs it was.\n")
    context = existing_corpus()
    point = head(context)
    added(run, tmp_path, "later", "# Later\n\nAdded after the point.\n")
    path = note(context, "changed")
    path.write_text(
        path.read_text(encoding="utf-8").replace("As it was.", "As it became."),
        encoding="utf-8",
    )
    Repository(context.corpus_root).commit("edit", scope="notes", summary="by hand")
    remove_a_document(
        context,
        Collection(root=context.corpus_root, name="notes"),
        Collection(root=context.corpus_root, name="notes").resolve("kept"),
    )
    return context, point


# ---------------------------------------------------------------------------
# Returning
# ---------------------------------------------------------------------------


def test_a_return_makes_the_collections_as_they_were(corpus: tuple[Context, str]):
    context, point = corpus

    return_corpus_to(context, point)

    assert titles(context) == ["changed", "kept"]
    assert "As it was." in note(context, "changed").read_text(encoding="utf-8")


def test_a_return_is_one_commit_naming_the_point(corpus: tuple[Context, str]):
    context, point = corpus

    return_corpus_to(context, point)

    latest = read_history(Repository(context.corpus_root), limit=1)[0]
    assert latest.operation == "return"
    assert latest.scope == "corpus"
    assert latest.summary.startswith(f"to {point[:8]}")
    assert git(context.corpus_root, "status", "--porcelain") == ""


def test_a_return_reports_what_it_changed(corpus: tuple[Context, str]):
    context, point = corpus

    returned = return_corpus_to(context, point)

    assert returned.added == 1
    assert returned.removed == 1
    assert returned.changed == 1


def test_a_return_is_undone_by_returning_to_the_point_before_it(
    corpus: tuple[Context, str],
):
    context, point = corpus
    before = head(context)
    return_corpus_to(context, point)

    return_corpus_to(context, before)

    assert titles(context) == ["changed", "later"]
    assert "As it became." in note(context, "changed").read_text(encoding="utf-8")


def test_work_not_yet_recorded_is_recorded_before_the_return(
    corpus: tuple[Context, str],
):
    context, point = corpus
    path = note(context, "later")
    path.write_text(path.read_text(encoding="utf-8") + "\nMine.\n", encoding="utf-8")

    return_corpus_to(context, point)

    operations = [
        entry.operation for entry in read_history(Repository(context.corpus_root))
    ]
    assert operations[:2] == ["return", "record"]
    recorded = read_history(Repository(context.corpus_root))[1].commit
    assert "Mine." in git(
        context.corpus_root,
        "show",
        f"{recorded}:{path.relative_to(context.corpus_root).as_posix()}",
    )


def test_a_collection_empty_at_the_point_is_emptied(run: CliRunner, tmp_path: Path):
    added(run, tmp_path, "first", "# First\n\nA note.\n")
    context = existing_corpus()
    point = head(context)
    source = tmp_path / "page.md"
    source.write_text("# Page\n\nA docs page.\n", encoding="utf-8")
    result = run.invoke(
        main, ["corpus", "add", "-d", "--project", "p", "--version", "1", str(source)]
    )
    assert result.exit_code == 0, result.output

    return_corpus_to(context, point)

    assert titles(context, "docs") == []
    assert titles(context) == ["first"]


def test_a_return_leaves_the_index_as_it_was_built(
    corpus: tuple[Context, str], run: CliRunner
):
    context, point = corpus
    assert run.invoke(main, ["corpus", "index", "--collection", "notes"]).exit_code == 0
    pointer = context.corpus_root / "index" / "notes" / "latest.json"
    built = pointer.read_bytes()

    return_corpus_to(context, point)

    assert pointer.read_bytes() == built


def test_returning_to_a_commit_that_is_not_there_changes_nothing(
    corpus: tuple[Context, str],
):
    context, _ = corpus
    before = head(context)

    with pytest.raises(InputError, match="not a point") as raised:
        return_corpus_to(context, "0123456789abcdef")

    assert raised.value.resolution == "kennis corpus history"

    assert head(context) == before


def test_returning_to_where_the_corpus_is_writes_nothing(corpus: tuple[Context, str]):
    context, _ = corpus
    before = head(context)

    returned = return_corpus_to(context, before)

    assert head(context) == before
    assert (returned.added, returned.removed, returned.changed) == (0, 0, 0)


def test_what_a_return_would_do_is_said_before_it_is_done(
    corpus: tuple[Context, str],
):
    context, point = corpus
    before = head(context)

    would = what_a_return_changes(Repository(context.corpus_root), point)

    assert [one.title for one in would.removed] == ["later"]
    assert [one.title for one in would.added] == ["kept"]
    assert [one.title for one in would.changed] == ["changed"]
    assert head(context) == before


# ---------------------------------------------------------------------------
# Removing and putting back
# ---------------------------------------------------------------------------


def test_a_removal_is_one_commit(corpus: tuple[Context, str]):
    context, _ = corpus

    latest = read_history(Repository(context.corpus_root), limit=1)[0]

    assert (latest.operation, latest.scope, latest.summary) == (
        "remove",
        "notes",
        "1 removed",
    )


def test_a_removal_says_what_it_removed_so_it_can_be_put_back(
    corpus: tuple[Context, str],
):
    context, _ = corpus
    removal = read_history(Repository(context.corpus_root), limit=1)[0].commit

    (gone,) = removed_in(Repository(context.corpus_root), removal)

    assert gone.title == "kept"
    restore_a_document(context, gone.document_id, commit=f"{removal}^")
    assert titles(context) == ["changed", "kept", "later"]
    latest = read_history(Repository(context.corpus_root), limit=1)[0]
    assert latest.operation == "restore"


def test_putting_back_a_document_not_at_the_commit_is_refused(
    corpus: tuple[Context, str],
):
    context, _ = corpus

    with pytest.raises(DocumentNotFound):
        restore_a_document(context, "no-such-id", commit="HEAD")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_corpus_return_asks_first_and_does_nothing_when_told_no(
    corpus: tuple[Context, str], run: CliRunner
):
    context, point = corpus
    before = head(context)

    result = run.invoke(main, ["corpus", "return", point[:8]], input="n\n")

    assert "later" in result.output
    assert head(context) == before


def test_corpus_return_returns_and_names_the_index_command(
    corpus: tuple[Context, str], run: CliRunner
):
    context, point = corpus

    result = run.invoke(main, ["corpus", "return", point[:8], "-y"])

    assert result.exit_code == 0, result.output
    assert titles(context) == ["changed", "kept"]
    assert "kennis corpus index" in result.output


def test_a_removal_that_swept_in_a_hand_edit_offers_only_what_it_removed(
    corpus: tuple[Context, str],
):
    """`Repository.commit` stages everything, so a removal made while
    another note was edited by hand records the edit too; only the
    document it removed is offered back."""
    context, _ = corpus
    path = note(context, "changed")
    path.write_text(path.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    notes = Collection(root=context.corpus_root, name="notes")
    remove_a_document(context, notes, notes.resolve("later"))
    removal = read_history(Repository(context.corpus_root), limit=1)[0].commit

    assert [
        one.title for one in removed_in(Repository(context.corpus_root), removal)
    ] == ["later"]
