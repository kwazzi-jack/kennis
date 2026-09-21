"""Whether an index still matches the corpus it was built over.

The index records the commit it was built from, so the question is answered
by git rather than by walking the corpus: `git diff --name-status` between
that commit and HEAD, plus the working tree's own status for anything not yet
committed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.history.freshness import index_freshness
from kennis.engine.history.repository import Repository, initialise_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    initialise_corpus(root)
    return root


def a_note(corpus: Path, name: str, body: str = "# A note\n\nBody.\n") -> Path:
    path = corpus / "notes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def a_wrapped_note(corpus: Path, name: str) -> Path:
    directory = corpus / "notes" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "content.md").write_text("# Wrapped\n\nBody.\n", encoding="utf-8")
    (directory / "figure.png").write_bytes(b"png")
    return directory


def committed(corpus: Path, summary: str = "1 added") -> str:
    recorded = Repository(corpus).commit("add", scope="notes", summary=summary)
    assert recorded is not None
    return recorded


def freshness(corpus: Path, built_from: str | None):
    return index_freshness(
        Repository(corpus), collection="notes", built_from=built_from
    )


# ---------------------------------------------------------------------------
# In step
# ---------------------------------------------------------------------------


def test_an_index_built_at_the_current_commit_is_in_step(corpus: Path):
    a_note(corpus, "one.md")
    head = committed(corpus)

    assert freshness(corpus, head).state == "in step"


def test_a_change_outside_the_collection_does_not_disturb_it(corpus: Path):
    """The index directory lives in the same repository and is rewritten
    wholesale by every build, so a query that did not scope itself to the
    collection would call every index stale the moment it was written."""
    a_note(corpus, "one.md")
    head = committed(corpus)

    (corpus / "index").mkdir(exist_ok=True)
    (corpus / "index" / "embeddings.npy").write_bytes(b"\x00" * 64)
    (corpus / "docs").mkdir(exist_ok=True)
    (corpus / "docs" / "elsewhere.md").write_text("# Docs\n", encoding="utf-8")

    assert freshness(corpus, head).state == "in step"


# ---------------------------------------------------------------------------
# Added, which is incomplete rather than wrong
# ---------------------------------------------------------------------------


def test_a_document_added_since_the_build_is_counted(corpus: Path):
    a_note(corpus, "one.md")
    head = committed(corpus)

    a_note(corpus, "two.md")
    committed(corpus)

    assert freshness(corpus, head).added == 1


def test_a_document_added_since_the_build_does_not_make_it_stale(corpus: Path):
    """The plan's test, and design section 15's rule: incomplete is not
    wrong. Between a `corpus add` and the `corpus index` that follows it, the
    index holds nothing false - it holds less."""
    a_note(corpus, "one.md")
    head = committed(corpus)

    a_note(corpus, "two.md")
    committed(corpus)

    assert freshness(corpus, head).state == "in step"


def test_a_document_added_but_not_yet_committed_is_still_counted(corpus: Path):
    """A user who edits by hand has not committed anything, and the index
    does not know about their work either way."""
    a_note(corpus, "one.md")
    head = committed(corpus)

    a_note(corpus, "two.md")

    assert freshness(corpus, head).added == 1


# ---------------------------------------------------------------------------
# Changed and gone, which are
# ---------------------------------------------------------------------------


def test_a_document_changed_since_the_build_is_reported(corpus: Path):
    """The plan's test: an index built, then a document edited, reports
    exactly one changed document."""
    note = a_note(corpus, "one.md")
    a_note(corpus, "two.md")
    head = committed(corpus, "2 added")

    note.write_text("# A note\n\nRevised body.\n", encoding="utf-8")
    committed(corpus, "1 changed")

    report = freshness(corpus, head)
    assert report.changed == 1
    assert report.state == "stale"


def test_an_uncommitted_edit_is_reported(corpus: Path):
    note = a_note(corpus, "one.md")
    head = committed(corpus)

    note.write_text("# A note\n\nEdited by hand.\n", encoding="utf-8")

    report = freshness(corpus, head)
    assert report.changed == 1
    assert report.state == "stale"


def test_a_deleted_document_is_reported(corpus: Path):
    note = a_note(corpus, "one.md")
    a_note(corpus, "two.md")
    head = committed(corpus, "2 added")

    note.unlink()
    committed(corpus, "1 removed")

    report = freshness(corpus, head)
    assert report.gone == 1
    assert report.state == "stale"


def test_a_document_both_committed_and_then_edited_counts_once(corpus: Path):
    """It appears in the commit diff and again in the working tree status,
    and it is one document either way."""
    note = a_note(corpus, "one.md")
    head = committed(corpus)

    note.write_text("# A note\n\nFirst revision.\n", encoding="utf-8")
    committed(corpus, "1 changed")
    note.write_text("# A note\n\nSecond revision.\n", encoding="utf-8")

    assert freshness(corpus, head).changed == 1


# ---------------------------------------------------------------------------
# Documents, not files
# ---------------------------------------------------------------------------


def test_a_wrapped_document_counts_once_however_many_files_changed(corpus: Path):
    """Three paths under one directory are one document, and counting files
    would report a paper with two figures as three changes."""
    a_note(corpus, "one.md")
    head = committed(corpus)

    a_wrapped_note(corpus, "A Paper")
    committed(corpus)

    assert freshness(corpus, head).added == 1


def test_an_asset_change_is_a_change_to_its_document(corpus: Path):
    directory = a_wrapped_note(corpus, "A Paper")
    head = committed(corpus)

    (directory / "figure.png").write_bytes(b"different png")

    report = freshness(corpus, head)
    assert report.changed == 1
    assert report.gone == 0


def test_the_collection_placeholder_is_not_a_document(corpus: Path):
    """`.gitkeep` exists so git keeps an empty collection directory. It must
    not be counted as a document, or a fresh corpus reports one of them."""
    head = Repository(corpus).head()

    assert freshness(corpus, head).added == 0


# ---------------------------------------------------------------------------
# When the question cannot be answered
# ---------------------------------------------------------------------------


def test_an_index_with_no_recorded_commit_is_unverifiable(corpus: Path):
    assert freshness(corpus, None).state == "unverifiable"


def test_a_commit_this_repository_has_never_seen_is_unverifiable(corpus: Path):
    """An index built on another machine names a commit that is not here.
    The honest answer is that the question cannot be answered, never that the
    answer is yes."""
    a_note(corpus, "one.md")
    committed(corpus)

    report = freshness(corpus, "0" * 40)

    assert report.state == "unverifiable"
    # A value, not a sentence: the two unverifiable cases are worded
    # differently by `kennis.render`, and the engine does not know how.
    assert report.unverifiable == "commit not in this corpus"


def test_unverifiable_is_never_read_as_in_step(corpus: Path):
    assert freshness(corpus, None).state != "in step"


# ---------------------------------------------------------------------------
# Renames
# ---------------------------------------------------------------------------


def test_a_renamed_document_is_reported_rather_than_missed(corpus: Path):
    """Whether git calls this a rename depends on a similarity heuristic, so
    kennis reads it in the safe direction: the old path is gone and the new
    one is added. A document that moved is a document the index no longer
    points at correctly either way."""
    note = a_note(corpus, "one.md")
    head = committed(corpus)

    note.rename(corpus / "notes" / "renamed.md")
    committed(corpus, "1 moved")

    report = freshness(corpus, head)
    assert report.gone == 1
    assert report.added == 1
    assert report.state == "stale"
