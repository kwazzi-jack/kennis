"""Reading what kennis did, and putting a document back as it was.

The commit messages were given a structure in step 1 - `add(notes): 3 added`
rather than "update" - precisely so this step could read them back.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kennis.engine.errors import DocumentNotFound
from kennis.engine.history.freshness import index_freshness
from kennis.engine.history.history import read_history, restore_document
from kennis.engine.history.repository import Repository, initialise_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    initialise_corpus(root)
    return root


def a_document(
    corpus: Path,
    name: str,
    *,
    collection: str = "notes",
    identifier: str = "aaaaaaaaaa",
    body: str = "Body.",
) -> Path:
    path = corpus / collection / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {identifier}\ntitle: A note\nowner: user\n---\n"
        f"\n# A note\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def recorded(
    corpus: Path, operation: str = "add", scope: str = "notes", summary: str = "1 added"
) -> str:
    commit = Repository(corpus).commit(operation, scope=scope, summary=summary)
    assert commit is not None
    return commit


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------


def test_history_reads_back_what_each_command_did(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus, "add", "notes", "1 added")

    entries = read_history(Repository(corpus))

    assert entries[0].operation == "add"
    assert entries[0].scope == "notes"
    assert entries[0].summary == "1 added"


def test_history_is_newest_first(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus, "add", "notes", "1 added")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb")
    recorded(corpus, "add", "notes", "2 added")

    summaries = [entry.summary for entry in read_history(Repository(corpus))]

    assert summaries[:2] == ["2 added", "1 added"]


def test_history_includes_the_corpus_being_created(corpus: Path):
    entries = read_history(Repository(corpus))

    assert entries[-1].operation == "init"
    assert entries[-1].scope == "corpus"


def test_each_entry_carries_its_commit_and_time(corpus: Path):
    a_document(corpus, "one.md")
    commit = recorded(corpus)

    entry = read_history(Repository(corpus))[0]

    assert entry.commit == commit
    assert isinstance(entry.when, datetime)
    assert entry.when.tzinfo is not None


def test_history_can_be_limited(corpus: Path):
    for number in range(5):
        a_document(corpus, f"note{number}.md", identifier=f"{number}aaaaaaaa")
        recorded(corpus)

    assert len(read_history(Repository(corpus), limit=3)) == 3


def test_history_can_be_filtered_to_one_collection(corpus: Path):
    """Git decides which commits touched those paths, rather than kennis
    inferring it from the scope in the message - a single commit can touch
    two collections, and git's answer is the true one."""
    a_document(corpus, "one.md", collection="notes")
    recorded(corpus, "add", "notes", "1 added")
    a_document(corpus, "paper.md", collection="literature", identifier="bbbbbbbbbb")
    recorded(corpus, "add", "literature", "1 added")

    entries = read_history(Repository(corpus), collection="literature")

    # The corpus's own creation touched `literature/` too, because each
    # collection holds a `.gitkeep` so git keeps the directory. That is git
    # answering truthfully rather than a filter leaking, so what the filter
    # must exclude is the commit that touched only `notes/`.
    assert "notes" not in [entry.scope for entry in entries]
    assert "literature" in [entry.scope for entry in entries]


def test_a_message_that_does_not_parse_is_kept(corpus: Path):
    """A corpus may hold a commit someone made by hand. A history that
    silently omits what it cannot categorise invents a history in which that
    did not happen."""
    a_document(corpus, "one.md")
    from kennis.engine.history.git import git

    git(["add", "--all", "."], cwd=corpus)
    git(["commit", "-m", "did something by hand"], cwd=corpus)

    entry = read_history(Repository(corpus))[0]

    assert entry.operation is None
    assert entry.summary == "did something by hand"


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------


def test_a_document_is_returned_to_a_previous_state(corpus: Path):
    """The plan's test: `corpus restore` returns a document to a previous
    state."""
    note = a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    note.write_text(
        note.read_text(encoding="utf-8").replace("First body.", "Second body."),
        encoding="utf-8",
    )
    recorded(corpus, "add", "notes", "1 changed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert "First body." in note.read_text(encoding="utf-8")


def test_restoring_reports_the_path_and_the_commit(corpus: Path):
    a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    a_document(corpus, "one.md", body="Second body.")
    recorded(corpus, "add", "notes", "1 changed")

    restored = restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert restored.path == "notes/one.md"
    assert restored.commit == before


def test_a_deleted_document_can_be_restored_by_its_identifier(corpus: Path):
    """The path cannot be found by walking the corpus, because the document
    is not there. It is resolved against history instead."""
    note = a_document(corpus, "one.md")
    before = recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert note.is_file()


def test_restoring_an_unknown_identifier_is_refused(corpus: Path):
    a_document(corpus, "one.md")
    commit = recorded(corpus)

    with pytest.raises(DocumentNotFound):
        restore_document(Repository(corpus), "zzzzzzzzzz", commit=commit)


def test_restoring_does_not_disturb_another_document(corpus: Path):
    a_document(corpus, "one.md", identifier="aaaaaaaaaa", body="First.")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb", body="Other.")
    before = recorded(corpus, "add", "notes", "2 added")
    a_document(corpus, "one.md", identifier="aaaaaaaaaa", body="Changed.")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb", body="Also changed.")
    recorded(corpus, "add", "notes", "2 changed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert "Also changed." in (corpus / "notes" / "two.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# And the index notices
# ---------------------------------------------------------------------------


def test_the_index_notices_a_restore(corpus: Path):
    """The plan's last test for this milestone. Nothing new is needed - a
    restore changes a file in the collection - but it is a claim about two
    parts fitting together, and those are the claims that quietly stop being
    true."""
    a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    a_document(corpus, "one.md", body="Second body.")
    built_at = recorded(corpus, "index", "notes", "1 indexed")

    assert (
        index_freshness(
            Repository(corpus), collection="notes", built_from=built_at
        ).state
        == "in step"
    )

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    report = index_freshness(
        Repository(corpus), collection="notes", built_from=built_at
    )
    assert report.state == "stale"
    assert report.changed == 1
