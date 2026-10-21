"""A write prepared in a mirror, then published all at once (14e, #507).

An operation's slow part runs against a mirror of the three collections,
inside the corpus's `.git`, holding no lock: nothing it writes is seen
until it is published. Publishing finds what changed by inode and mode,
journals every path, places them and commits. A failure while placing, or
a journal found at the next start, puts back exactly those paths - never a
whole-tree reset, which would discard a person's edit elsewhere.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from kennis.engine import staging
from kennis.engine.atomic import make_read_only, remove_file
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, write_document
from kennis.engine.corpus.layout import STAGING_DIRNAME
from kennis.engine.corpus.schema import NoteFrontmatter
from kennis.engine.errors import HistoryUnwritable, PublishRefused
from kennis.engine.history.repository import Repository, initialise_corpus
from kennis.engine.staging import (
    journal_path,
    mirrored,
    publish,
    recover,
)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def a_note(root: Path, identifier: str, body: str = "Text.\n") -> Path:
    frontmatter = NoteFrontmatter.model_validate(
        {
            "id": identifier,
            "title": identifier,
            "owner": "user",
            "source": {"from": "inline:", "via": "remember", "format": "markdown"},
        }
    )
    path = root / "notes" / f"{identifier}.md"
    write_document(path, frontmatter=frontmatter, body=body)
    return path


def committed(corpus: Path, *notes: str) -> None:
    for identifier in notes:
        a_note(corpus, identifier)
    Repository(corpus).commit("remember", scope="notes", summary="setup")


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


def commit_count(corpus: Path) -> int:
    counted = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=corpus,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    return int(counted.stdout)


def subjects_since(corpus: Path, commit: str | None) -> list[str]:
    """The subjects of the commits after `commit`, oldest first."""
    logged = subprocess.run(
        ["git", "log", "--reverse", "--format=%s", f"{commit}..HEAD"],
        cwd=corpus,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    return logged.stdout.splitlines()


def ids_in(root: Path) -> list[str]:
    return sorted(
        document.id
        for document in Collection(root=root, name="notes").contents().documents
    )


def is_read_only(path: Path) -> bool:
    return not path.stat().st_mode & stat.S_IWRITE


# ---------------------------------------------------------------------------
# Preparing touches nothing


def test_writes_in_the_mirror_are_not_seen_until_published(corpus: Path):
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "second")
        assert ids_in(corpus) == ["first"]
        assert ids_in(mirror.root) == ["first", "second"]
        publish(mirror, operation="remember", scope="notes", summary="1 documents")

    assert ids_in(corpus) == ["first", "second"]
    assert git_status(corpus) == ""


def test_a_mirror_left_unpublished_changes_nothing(corpus: Path):
    committed(corpus, "first")
    head = Repository(corpus).head()

    with pytest.raises(RuntimeError), mirrored(corpus) as mirror:
        a_note(mirror.root, "second")
        (mirror.root / "notes" / "first.md").unlink()
        raise RuntimeError("interrupted while preparing")

    assert ids_in(corpus) == ["first"]
    assert Repository(corpus).head() == head
    assert git_status(corpus) == ""
    assert not any(staging.staging_root(corpus).iterdir())


def test_sealing_a_file_in_the_mirror_does_not_reach_the_corpus(corpus: Path):
    """A hard link shares its mode with the file it links to, so a seal on
    the link would seal the person's note before anything was published."""
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        staging_path = mirror.root / "notes" / "first.md"
        make_read_only(staging_path)

        assert not is_read_only(corpus / "notes" / "first.md")


def test_removing_a_read_only_file_in_the_mirror_does_not_reach_the_corpus(
    corpus: Path,
):
    committed(corpus, "first")
    real = corpus / "notes" / "first.md"
    real.chmod(0o444)

    with mirrored(corpus) as mirror:
        remove_file(mirror.root / "notes" / "first.md")

        assert real.is_file()
        assert is_read_only(real)


# ---------------------------------------------------------------------------
# Publishing


def test_publish_places_what_was_added_changed_and_removed_in_one_commit(
    corpus: Path,
):
    committed(corpus, "kept", "changed", "removed")
    commits_before = commit_count(corpus)

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "added")
        a_note(mirror.root, "changed", body="New text.\n")
        (mirror.root / "notes" / "removed.md").unlink()
        made = publish(mirror, operation="add", scope="notes", summary="2 changes")

    assert made is not None
    assert ids_in(corpus) == ["added", "changed", "kept"]
    assert "New text." in (corpus / "notes" / "changed.md").read_text("utf-8")
    assert commit_count(corpus) == commits_before + 1
    assert git_status(corpus) == ""
    assert not journal_path(corpus).exists()


def test_a_mode_change_alone_is_published(corpus: Path):
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        make_read_only(mirror.root / "notes" / "first.md")
        publish(mirror, operation="move", scope="notes", summary="sealed")

    assert is_read_only(corpus / "notes" / "first.md")


def test_a_directory_emptied_in_the_mirror_goes_from_the_corpus(corpus: Path):
    """A docs version removed is a folder removed."""
    group = corpus / "notes" / "radio"
    group.mkdir()
    (group / "beams.md").write_text((corpus / "README.md").read_text(), "utf-8")
    Repository(corpus).commit("add", scope="notes", summary="setup")

    with mirrored(corpus) as mirror:
        staging_group = mirror.root / "notes" / "radio"
        for child in staging_group.iterdir():
            child.unlink()
        staging_group.rmdir()
        publish(mirror, operation="remove", scope="notes", summary="1 removed")

    assert not group.exists()


def test_nothing_changed_makes_no_commit(corpus: Path):
    committed(corpus, "first")
    head = Repository(corpus).head()

    with mirrored(corpus) as mirror:
        made = publish(mirror, operation="add", scope="notes", summary="none")

    assert made is None
    assert Repository(corpus).head() == head


def test_a_hand_edit_is_recorded_under_its_own_name_before_the_publish(
    corpus: Path,
):
    """#525 item 3: the publish's commit stages with `git add --all .`, so
    without the record the edit would be claimed by the add."""
    committed(corpus, "theirs")
    head = Repository(corpus).head()
    theirs = corpus / "notes" / "theirs.md"
    theirs.write_text(theirs.read_text("utf-8") + "An edit of theirs.\n", "utf-8")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "second")
        publish(mirror, operation="add", scope="notes", summary="1")

    assert subjects_since(corpus, head) == [
        "record(corpus): what was not yet recorded",
        "add(notes): 1",
    ]
    assert git_status(corpus) == ""


def test_a_publish_with_nothing_to_place_records_nothing(corpus: Path):
    """A repeated note changes nothing, so it must not commit the person's
    half-finished edit either - not even under its own name."""
    committed(corpus, "theirs")
    head = Repository(corpus).head()
    theirs = corpus / "notes" / "theirs.md"
    theirs.write_text(theirs.read_text("utf-8") + "Half finished.\n", "utf-8")

    with mirrored(corpus) as mirror:
        made = publish(mirror, operation="add", scope="notes", summary="none")

    assert made is None
    assert Repository(corpus).head() == head
    assert git_status(corpus) == " M notes/theirs.md\n"


def test_another_write_while_preparing_refuses_the_publish(corpus: Path):
    """The precondition: what the operation replaced must still be what it
    replaced, or a write that landed meanwhile would be overwritten."""
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "first", body="From the operation.\n")
        a_note(corpus, "first", body="From another write.\n")

        with pytest.raises(PublishRefused):
            publish(mirror, operation="add", scope="notes", summary="1")

    assert "From another write." in (corpus / "notes" / "first.md").read_text("utf-8")


def test_a_new_file_someone_else_created_meanwhile_refuses_the_publish(
    corpus: Path,
):
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "second", body="From the operation.\n")
        a_note(corpus, "second", body="From another write.\n")

        with pytest.raises(PublishRefused):
            publish(mirror, operation="add", scope="notes", summary="1")

    assert "another write" in (corpus / "notes" / "second.md").read_text("utf-8")


# ---------------------------------------------------------------------------
# A failure while placing, and a crash


@dataclass
class FailAfter:
    """`os.replace`, failing on the call after `allowed` placed files."""

    allowed: int
    calls: int = 0

    def __post_init__(self) -> None:
        self.real = os.replace

    def __call__(self, source: str | Path, target: str | Path) -> None:
        if Path(target).suffix == ".md" and STAGING_DIRNAME in str(source):
            self.calls += 1
            if self.calls > self.allowed:
                raise OSError("the disk filled while placing")
        self.real(source, target)


def test_a_failure_while_placing_puts_back_exactly_what_was_placed(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """Fails between the first file placed and the second (#63's rule for
    an ordering property), with a person's uncommitted edit elsewhere that
    the rollback must not touch - recorded under its own name before
    anything is placed (#525 item 3), and kept by the rollback."""
    committed(corpus, "first", "second", "theirs")
    head = Repository(corpus).head()
    theirs = corpus / "notes" / "theirs.md"
    theirs.write_text(theirs.read_text("utf-8") + "An edit of theirs.\n", "utf-8")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "first", body="Changed one.\n")
        a_note(mirror.root, "second", body="Changed two.\n")
        a_note(mirror.root, "third")
        failing = FailAfter(allowed=1)
        monkeypatch.setattr(os, "replace", failing)
        with pytest.raises(OSError, match="disk filled"):
            publish(mirror, operation="add", scope="notes", summary="3")
    assert failing.calls == 2, "the failure did not fall between two placements"

    assert subjects_since(corpus, head) == ["record(corpus): what was not yet recorded"]
    assert ids_in(corpus) == ["first", "second", "theirs"]
    assert "Changed" not in (corpus / "notes" / "first.md").read_text("utf-8")
    assert "An edit of theirs." in theirs.read_text("utf-8")
    assert git_status(corpus) == ""
    assert not journal_path(corpus).exists()


def test_a_commit_git_refuses_puts_back_everything_placed(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """The last step of a publish failing: every file is placed, the commit
    refused, and the corpus goes back to what HEAD holds."""
    committed(corpus, "first")
    head = Repository(corpus).head()

    real_commit = Repository.commit

    def refused(
        self: Repository, operation: str, *, scope: str, summary: str
    ) -> str | None:
        if operation == "record":
            return real_commit(self, operation, scope=scope, summary=summary)
        raise HistoryUnwritable("git refused the commit")

    with mirrored(corpus) as mirror:
        a_note(mirror.root, "first", body="Changed.\n")
        a_note(mirror.root, "second")
        monkeypatch.setattr(Repository, "commit", refused)
        with pytest.raises(HistoryUnwritable):
            publish(mirror, operation="add", scope="notes", summary="2")

    assert Repository(corpus).head() == head
    assert ids_in(corpus) == ["first"]
    assert "Changed" not in (corpus / "notes" / "first.md").read_text("utf-8")
    assert git_status(corpus) == ""
    assert not journal_path(corpus).exists()


def test_a_journal_left_by_a_crash_is_rolled_back_at_the_next_start(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """Killed while placing: nothing ran the rollback, so the journal is
    still there and the next start puts the corpus back."""
    committed(corpus, "first")
    head = Repository(corpus).head()

    with mirrored(corpus) as mirror, monkeypatch.context() as killed:
        a_note(mirror.root, "first", body="Half published.\n")
        a_note(mirror.root, "second")
        killed.setattr(staging, "_roll_back", lambda corpus_root: None)
        killed.setattr(os, "replace", FailAfter(allowed=1))
        with pytest.raises(OSError):
            publish(mirror, operation="add", scope="notes", summary="2")
    assert journal_path(corpus).exists()
    assert "Half published." in (corpus / "notes" / "first.md").read_text("utf-8")

    rolled_back = recover(corpus)

    assert rolled_back == "add"
    assert Repository(corpus).head() == head
    assert ids_in(corpus) == ["first"]
    assert git_status(corpus) == ""
    assert not journal_path(corpus).exists()


def test_a_crash_after_the_commit_takes_the_commit_back_too(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """Killed between the commit and removing the journal: the journal
    still names the commit before, so the next start returns HEAD there
    as well as the files."""
    committed(corpus, "first")
    head = Repository(corpus).head()
    real_commit = Repository.commit

    def committed_then_killed(
        self: Repository, operation: str, *, scope: str, summary: str
    ) -> str | None:
        made = real_commit(self, operation, scope=scope, summary=summary)
        if operation == "record":
            return made
        raise KeyboardInterrupt

    with mirrored(corpus) as mirror, monkeypatch.context() as killed:
        a_note(mirror.root, "second")
        killed.setattr(staging, "_roll_back", lambda corpus_root: None)
        killed.setattr(Repository, "commit", committed_then_killed)
        with pytest.raises(KeyboardInterrupt):
            publish(mirror, operation="add", scope="notes", summary="1")
    assert Repository(corpus).head() != head

    recover(corpus)

    assert Repository(corpus).head() == head
    assert ids_in(corpus) == ["first"]
    assert git_status(corpus) == ""


def test_recovery_with_no_journal_does_nothing(corpus: Path):
    committed(corpus, "first")

    assert recover(corpus) is None
    assert git_status(corpus) == ""


def test_recovery_clears_leftovers_a_killed_process_leaves(corpus: Path):
    """A staging folder, a `.tmp` from `replace_file`, and git's own
    `index.lock`, which stops every later commit until it goes."""
    committed(corpus, "first")
    leftover = staging.staging_root(corpus) / "abandoned"
    leftover.mkdir(parents=True)
    temporary = corpus / "notes" / "tmpabc123.tmp"
    temporary.write_text("half", "utf-8")
    (corpus / ".git" / "index.lock").write_text("", "utf-8")

    recover(corpus)

    assert not leftover.exists()
    assert not temporary.exists()
    assert not (corpus / ".git" / "index.lock").exists()
    a_note(corpus, "second")
    assert Repository(corpus).commit("remember", scope="notes", summary="1")


# ---------------------------------------------------------------------------
# What comes back names the corpus, not the mirror


@dataclass(frozen=True)
class Report:
    path: Path
    paths: tuple[Path, ...]
    said: str
    document: Document | None = None


def test_paths_in_what_comes_back_name_the_corpus(corpus: Path):
    committed(corpus, "first")

    with mirrored(corpus) as mirror:
        written = a_note(mirror.root, "second")
        document = Collection(root=mirror.root, name="notes").resolve("second")
        report = Report(
            path=written,
            paths=(written, Path("/elsewhere/x.md")),
            said=f"wrote {written}",
            document=document,
        )

        rebased = mirror.rebased(report)

    assert rebased.path == corpus / "notes" / "second.md"
    assert rebased.paths == (corpus / "notes" / "second.md", Path("/elsewhere/x.md"))
    assert rebased.said == f"wrote {corpus / 'notes' / 'second.md'}"
    assert rebased.document is not None
    assert rebased.document.md_path == corpus / "notes" / "second.md"
