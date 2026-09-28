"""The mutating sequence, shared by every front end.

Unit 9f. `operations.py` holds what `cli/commands/corpus.py` used to:
take the corpus lock, restore anything deleted by hand, call the
engine, commit. The graphical interface needs all four and may not
import the command line to get them.

Concern #317 is why the command line was rewired in the same unit
rather than left with its own copy: leaving it out when `writing.py`
was extracted hid that `writing.py` had no commit coverage at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import CorpusBusy
from kennis.engine.history.git import git
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock
from kennis.operations import (
    add_documents,
    build_indexes,
    restore_hand_deletions,
    synchronise_bundle,
)


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
    path.write_text(f"# {name}\n\nSome words about trees.\n", encoding="utf-8")
    return path


def only_note(corpus_root: Path) -> Path:
    found = sorted((corpus_root / "notes").rglob("*.md"))
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------------------
# The sequence
# ---------------------------------------------------------------------------


def test_adding_takes_the_lock_writes_and_commits(isolated: Path):
    context = existing_corpus()
    before = Repository(context.corpus_root).head()

    report = add_documents(
        context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions()
    )

    assert len(report.outcomes) == 1
    assert only_note(context.corpus_root).is_file()
    after = Repository(context.corpus_root).head()
    assert after is not None and after != before
    assert Repository(context.corpus_root).is_clean()


def test_adding_is_refused_while_the_corpus_is_busy(isolated: Path):
    """`timeout=0`, so a second writer is told rather than left with a
    terminal that has stopped. The graphical interface presents this as
    a state to retry from, not as an error page."""
    context = existing_corpus()

    with corpus_lock(context.corpus_root), pytest.raises(CorpusBusy):
        add_documents(
            context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions()
        )


def test_a_hand_deletion_is_restored_before_the_commit_is_made(isolated: Path):
    """An ordering property, and one that must fail *between* its two
    events rather than before both of them.

    A deletion restored *after* the commit leaves the file on disk and
    the deletion in history, because `Repository.commit` stages with
    `git add --all .`. So the file existing is not enough: the commit
    this add makes must record no deletion of it. Concern #128.
    """
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "first.md"))], AddOptions())
    deleted = only_note(context.corpus_root)
    held = deleted.read_text(encoding="utf-8")
    deleted.unlink()

    add_documents(
        context, "notes", [str(a_source(isolated, "second.md"))], AddOptions()
    )

    assert deleted.is_file()
    assert deleted.read_text(encoding="utf-8") == held
    touched = git(
        ["show", "--name-status", "--format=", "HEAD"], cwd=context.corpus_root
    ).lines()
    assert not [line for line in touched if line.startswith("D\t")], touched


def test_the_restore_reports_what_it_put_back(isolated: Path):
    """It returns rather than prints, so each front end says it its own
    way. That is the whole reason it left `cli/`."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    only_note(context.corpus_root).unlink()

    with corpus_lock(context.corpus_root):
        restored = restore_hand_deletions(context)

    assert len(restored) == 1
    assert restored[0].restored


def test_indexing_skips_an_empty_collection_and_commits_once(isolated: Path):
    """`build_index` refuses an empty collection by design, and two of
    the three are empty on most corpora, so asking for all of them must
    not fail on that account."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    before = Repository(context.corpus_root).head()

    result = build_indexes(context)

    assert [index.collection for index in result.built] == ["notes"]
    assert result.documents == 1
    assert result.chunks >= 1
    assert Repository(context.corpus_root).head() != before


def test_indexing_names_the_backend_it_used(isolated: Path):
    """The fields, not a sentence: a front end that wants to say "using
    ..." has both, and one that says nothing ignores them. With no
    embedding backend there is no model, which is a different sentence
    rather than an empty one."""
    result = build_indexes(existing_corpus())

    assert result.model_kind is None and result.model_name is None


def test_indexing_one_collection_leaves_the_others_alone(isolated: Path):
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())

    result = build_indexes(context, "literature")

    assert result.built == []


# ---------------------------------------------------------------------------
# The two that are deliberately different
# ---------------------------------------------------------------------------


def test_a_bundle_sync_makes_no_commit_in_the_users_repository(
    isolated: Path, tmp_path: Path
):
    """kennis does not commit here: the bundle is in the user's
    repository, and committing there would take over their version
    control."""
    project = tmp_path / "project"
    project.mkdir()
    git(["init"], cwd=project)
    bundle = project / ".context"
    bundle.mkdir()

    synchronise_bundle(bundle, existing_corpus())

    assert git(["log", "--oneline"], cwd=project).lines() == []


def test_the_collection_an_add_writes_to_is_the_one_asked_for(isolated: Path):
    context = existing_corpus()

    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())

    assert Collection(root=context.corpus_root, name="notes").contents().documents
    assert not Collection(root=context.corpus_root, name="docs").contents().documents
