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

import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from held import held_for_a_moment
from kennis import operations, writing
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.context.bundle import init_bundle
from kennis.engine.corpus.add import AddOptions, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.events import Outcome
from kennis.engine.history.git import git
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.history.repository import Repository
from kennis.engine.rag.index import read_manifest
from kennis.engine.staging import staging_root
from kennis.operations import (
    add_documents,
    build_indexes,
    restore_hand_deletions,
    return_corpus_to,
    synchronise_bundle,
)
from kennis.publishing import exclusively
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


def test_adding_waits_for_a_publish_under_way_and_then_lands(isolated: Path):
    """The corpus held to publish by another write: the add is not refused
    (14e), and it finishes only after the holder lets go."""
    context = existing_corpus()

    with held_for_a_moment(context.corpus_root) as hold:
        add_documents(
            context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions()
        )
        finished = time.monotonic()

    assert finished >= hold.released
    assert only_note(context.corpus_root).is_file()


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


def test_writing_a_note_restores_a_hand_deletion_first(isolated: Path):
    """`remember` from any front end - an agent's included - commits with
    `git add --all .` as `add` does, so it restores as `add` does."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "first.md"))], AddOptions())
    deleted = only_note(context.corpus_root)
    deleted.unlink()
    restored: list[OutOfBandChange] = []

    write_note(existing_corpus(), "A second thought about trees.", restored=restored)

    assert deleted.is_file()
    assert [change.path for change in restored] == [
        deleted.relative_to(context.corpus_root).as_posix()
    ]
    touched = git(
        ["show", "--name-status", "--format=", "HEAD"], cwd=context.corpus_root
    ).lines()
    assert not [line for line in touched if line.startswith("D\t")], touched


def test_an_add_that_fails_part_way_leaves_the_corpus_as_it_was(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """All or nothing (14e, #507): a document written before the failure
    was written in the mirror, which is discarded, so the corpus, its
    history and its working tree are as they were and no mirror is left."""
    context = existing_corpus()
    before = Repository(context.corpus_root).head()

    def writes_then_fails(
        target: Collection, identifiers: list[str], options: AddOptions, **rest: object
    ) -> object:
        add_notes(target, [str(a_source(isolated, "trees.md"))])
        raise OSError(28, "No space left on device")

    monkeypatch.setitem(operations._ADDERS, "notes", writes_then_fails)

    with pytest.raises(OSError):
        add_documents(context, "notes", ["anything"], AddOptions())

    assert Repository(context.corpus_root).head() == before
    assert Repository(context.corpus_root).is_clean()
    assert not list((context.corpus_root / "notes").rglob("*.md"))
    assert not any(staging_root(context.corpus_root).glob("*"))


def test_running_a_failed_add_again_adds_everything(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """What the window and the terminal tell the reader to do after a
    failure part-way: nothing of the first run was kept, so the second
    adds both documents."""
    context = existing_corpus()
    first, second = a_source(isolated, "first.md"), a_source(isolated, "second.md")
    real = operations._ADDERS["notes"]

    def stops_after_the_first(
        target: Collection, identifiers: list[str], options: AddOptions, **rest: object
    ) -> object:
        real(target, identifiers[:1], options)
        raise OSError(28, "No space left on device")

    monkeypatch.setitem(operations._ADDERS, "notes", stops_after_the_first)
    with pytest.raises(OSError):
        add_documents(context, "notes", [str(first), str(second)], AddOptions())
    monkeypatch.setitem(operations._ADDERS, "notes", real)

    again = add_documents(context, "notes", [str(first), str(second)], AddOptions())

    assert [outcome.outcome for outcome in again.outcomes] == [
        Outcome.ADDED,
        Outcome.ADDED,
    ]


def test_adding_the_folder_that_holds_the_corpus_does_not_copy_it(isolated: Path):
    """The window's chooser walks up from home, and "Choose this folder"
    on the folder holding the corpus copied the corpus into itself, with
    the search history and the configuration beside it as notes."""
    context = existing_corpus()
    (isolated / "config" / "credentials.toml").parent.mkdir(exist_ok=True)
    (isolated / "config" / "credentials.toml").write_text("key = 'secret'\n")
    a_source(isolated, "trees.md")

    report = add_documents(context, "notes", [str(isolated)], AddOptions())

    added = [outcome.identifier for outcome in report.outcomes if outcome.path]
    assert [Path(name).name for name in added] == ["trees.md"]
    copied = sorted(
        path.relative_to(context.corpus_root).as_posix()
        for path in (context.corpus_root / "notes").rglob("*.md")
    )
    assert copied == ["notes/sources/trees.md"]


def test_the_restore_reports_what_it_put_back(isolated: Path):
    """It returns rather than prints, so each front end says it its own
    way. That is the whole reason it left `cli/`."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    only_note(context.corpus_root).unlink()

    with exclusively(context.corpus_root):
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
    bundle = init_bundle(project).path

    synchronise_bundle(bundle, existing_corpus())

    assert git(["log", "--oneline"], cwd=project).lines() == []


def test_the_collection_an_add_writes_to_is_the_one_asked_for(isolated: Path):
    context = existing_corpus()

    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())

    assert Collection(root=context.corpus_root, name="notes").contents().documents
    assert not Collection(root=context.corpus_root, name="docs").contents().documents


def changed_by(corpus_root: Path, commit: str) -> list[str]:
    return git(
        ["show", "--name-only", "--format=", commit], cwd=corpus_root
    ).stdout.split()


def subjects(corpus_root: Path, count: int) -> list[str]:
    return git(["log", f"-{count}", "--format=%s"], cwd=corpus_root).stdout.split("\n")[
        :count
    ]


@pytest.mark.parametrize("write", ["add", "note", "index", "return"])
def test_a_hand_edit_is_recorded_before_the_write_under_its_own_name(
    isolated: Path, write: str
):
    """#525 item 3 (Brian, 2026-10-21): the write's commit carries only what
    the write did, and what someone changed by hand is recorded first, as
    `return` already does - so history says who made each change."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    edited = only_note(context.corpus_root)
    edited.write_text(edited.read_text("utf-8") + "\nAn edit by hand.\n", "utf-8")
    edited_name = edited.relative_to(context.corpus_root).as_posix()

    point = Repository(context.corpus_root).head()
    assert point is not None
    if write == "add":
        add_documents(
            context, "notes", [str(a_source(isolated, "elms.md"))], AddOptions()
        )
    elif write == "note":
        write_note(context, "Elms suffered from disease.", title="Elms")
    elif write == "index":
        build_indexes(context, "notes")
    else:
        return_corpus_to(context, point)

    newest, recorded = subjects(context.corpus_root, 2)
    assert recorded == "record(corpus): what was not yet recorded"
    assert newest.startswith(
        {
            "add": "add(notes)",
            "note": "remember(notes)",
            "index": "index(notes)",
            "return": "return(corpus)",
        }[write]
    )
    assert changed_by(context.corpus_root, "HEAD~1") == [edited_name]
    if write != "return":
        # A return to the point before the edit puts the file back, which
        # is its own commit's business; the edit is still kept, in HEAD~1.
        assert edited_name not in changed_by(context.corpus_root, "HEAD")
    assert Repository(context.corpus_root).is_clean()


def test_a_clean_corpus_gets_no_record_commit(isolated: Path):
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())

    write_note(context, "Elms suffered from disease.", title="Elms")

    assert not any(
        subject.startswith("record(") for subject in subjects(context.corpus_root, 5)
    )


def test_a_note_whose_publish_fails_is_not_in_the_index(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """#525 item 2 (Brian, 2026-10-21): the index is built after the note is
    published. Built before, a failed publish left the index naming a note
    that was not on disk, and a search found a hit nobody could open."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    build_indexes(context, "notes")
    root = index_root(context.corpus_root)
    before = read_manifest(root, "notes")
    assert before is not None

    def refused(*arguments: object, **options: object) -> object:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(writing, "publish", refused)
    with pytest.raises(OSError):
        write_note(context, "Elms suffered from disease.", title="Elms")

    after = read_manifest(root, "notes")
    assert after is not None
    assert after.documents == before.documents


def test_a_note_whose_index_fails_is_held_and_says_it_is_not_indexed(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """The failure the new order allows: published, then not indexed. The
    note is held and committed, and the report says `unindexed` - not
    `deferred`, whose words say another build holds the index."""
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    build_indexes(context, "notes")

    def failing(*arguments: object, **options: object) -> object:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(writing, "index_note", failing)
    report = write_note(context, "Elms suffered from disease.", title="Elms")

    assert report.index_outcome == "unindexed"
    assert report.path.exists()
    assert subjects(context.corpus_root, 1)[0].startswith("remember(notes)")
    assert Repository(context.corpus_root).is_clean()


def test_a_published_note_is_indexed_and_says_so(isolated: Path):
    context = existing_corpus()
    add_documents(context, "notes", [str(a_source(isolated, "trees.md"))], AddOptions())
    build_indexes(context, "notes")

    report = write_note(context, "Elms suffered from disease.", title="Elms")

    assert report.index_outcome == "indexed"
    assert report.chunk_count == 1
    manifest = read_manifest(index_root(context.corpus_root), "notes")
    assert manifest is not None
    assert any("Elms" in name for name in manifest.documents)
