"""Changes someone made to the corpus without going through kennis.

The corpus is a directory of real files, so someone will eventually edit,
delete or drop one in by hand. Git makes every such change visible, and the
governing rule is one sentence: kennis never loses data, and every
out-of-band change is reported alongside the command that would have done it
properly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.history.outofband import (
    detect_changes,
    restore_deletions,
)
from kennis.engine.history.repository import Repository, initialise_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    initialise_corpus(root)
    return root


def a_document(
    corpus: Path, name: str, *, owner: str = "user", identifier: str = "aaaaaaaaaa"
) -> Path:
    path = corpus / "notes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "id: " + identifier + "\n"
        "title: A note\n"
        "owner: " + owner + "\n"
        "---\n\n# A note\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def recorded(corpus: Path) -> None:
    Repository(corpus).commit("add", scope="notes", summary="1 added")


def changes(corpus: Path):
    return detect_changes(Repository(corpus))


# ---------------------------------------------------------------------------
# Nothing to report
# ---------------------------------------------------------------------------


def test_a_clean_corpus_reports_nothing(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus)

    assert changes(corpus) == []


# ---------------------------------------------------------------------------
# Edited
# ---------------------------------------------------------------------------


def test_a_document_edited_by_hand_is_reported(corpus: Path):
    """The plan's test: a document edited outside kennis is reported and not
    overwritten."""
    note = a_document(corpus, "one.md")
    recorded(corpus)
    note.write_text(
        note.read_text(encoding="utf-8") + "\nAdded by hand.\n", encoding="utf-8"
    )

    reported = changes(corpus)

    assert [change.kind for change in reported] == ["edited"]
    assert reported[0].document_id == "aaaaaaaaaa"


def test_an_edit_is_never_overwritten(corpus: Path):
    note = a_document(corpus, "one.md")
    recorded(corpus)
    edited = note.read_text(encoding="utf-8") + "\nAdded by hand.\n"
    note.write_text(edited, encoding="utf-8")

    detect_changes(Repository(corpus))
    restore_deletions(Repository(corpus), changes(corpus))

    assert note.read_text(encoding="utf-8") == edited


def test_an_edit_to_the_users_own_document_is_only_noted(corpus: Path):
    """Nothing to resolve - it is theirs. The only consequence is that the
    index is now behind.

    Asserted as facts. What is *said* about them is `kennis.render`'s, and
    is tested there.
    """
    note = a_document(corpus, "one.md", owner="user")
    recorded(corpus)
    note.write_text(note.read_text(encoding="utf-8") + "\nMine.\n", encoding="utf-8")

    change = changes(corpus)[0]

    assert change.kind == "edited"
    assert change.owner == "user"
    assert change.restored is False


def test_an_edit_to_a_pack_owned_document_is_reported_with_its_owner(corpus: Path):
    """Reverting is the resolution the user may choose, not the action kennis
    takes on noticing - so what the engine records is who owns it, and the
    ways forward are composed from that where the words live."""
    note = a_document(corpus, "one.md", owner="pack:boepie")
    recorded(corpus)
    note.write_text(note.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")

    change = changes(corpus)[0]

    assert change.kind == "edited"
    assert change.owner == "pack:boepie"
    assert change.document_id == "aaaaaaaaaa"


# ---------------------------------------------------------------------------
# Deleted
# ---------------------------------------------------------------------------


def test_a_deleted_document_is_reported(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus)
    (corpus / "notes" / "one.md").unlink()

    reported = changes(corpus)

    assert [change.kind for change in reported] == ["deleted"]


def test_a_deleted_documents_owner_is_read_from_history(corpus: Path):
    """The file is gone, so the only place its frontmatter still exists is
    the last commit."""
    a_document(corpus, "one.md", owner="pack:boepie")
    recorded(corpus)
    (corpus / "notes" / "one.md").unlink()

    assert changes(corpus)[0].owner == "pack:boepie"


def test_a_deleted_document_is_restored(corpus: Path):
    """The plan's test: a document deleted outside kennis is restored and
    reported. An out-of-band delete carries no record of intent, and treating
    an accident as an instruction is the more expensive mistake."""
    note = a_document(corpus, "one.md")
    recorded(corpus)
    original = note.read_text(encoding="utf-8")
    note.unlink()

    restore_deletions(Repository(corpus), changes(corpus))

    assert note.read_text(encoding="utf-8") == original


def test_restoring_reports_what_it_put_back(corpus: Path):
    """The user deleted something and got it back; being told is the
    difference between kennis being trustworthy and kennis being haunted."""
    a_document(corpus, "one.md")
    recorded(corpus)
    (corpus / "notes" / "one.md").unlink()

    restored = restore_deletions(Repository(corpus), changes(corpus))

    assert [change.kind for change in restored] == ["deleted"]
    assert restored[0].restored is True
    assert restored[0].path == "notes/one.md"


def test_a_deletion_is_restored_whoever_owned_it(corpus: Path):
    a_document(corpus, "mine.md", owner="user", identifier="aaaaaaaaaa")
    a_document(corpus, "theirs.md", owner="pack:boepie", identifier="bbbbbbbbbb")
    recorded(corpus)
    (corpus / "notes" / "mine.md").unlink()
    (corpus / "notes" / "theirs.md").unlink()

    restore_deletions(Repository(corpus), changes(corpus))

    assert (corpus / "notes" / "mine.md").is_file()
    assert (corpus / "notes" / "theirs.md").is_file()


def test_restoring_a_deletion_does_not_discard_an_edit(corpus: Path):
    """Restoring is per path, not a whole-tree reset: a reset would discard
    the edits in the same working tree, which rule one says never to
    discard."""
    a_document(corpus, "gone.md", identifier="aaaaaaaaaa")
    edited = a_document(corpus, "edited.md", identifier="bbbbbbbbbb")
    recorded(corpus)
    (corpus / "notes" / "gone.md").unlink()
    kept = edited.read_text(encoding="utf-8") + "\nEdited by hand.\n"
    edited.write_text(kept, encoding="utf-8")

    restore_deletions(Repository(corpus), changes(corpus))

    assert (corpus / "notes" / "gone.md").is_file()
    assert edited.read_text(encoding="utf-8") == kept


def test_a_wrapped_document_is_restored_with_its_assets(corpus: Path):
    """Deleting the directory removes several paths, and the document is not
    back until all of them are."""
    directory = corpus / "notes" / "A Paper"
    directory.mkdir(parents=True)
    (directory / "content.md").write_text(
        "---\nid: aaaaaaaaaa\ntitle: A Paper\nowner: user\n---\n\n# A Paper\n",
        encoding="utf-8",
    )
    (directory / "figure.png").write_bytes(b"png")
    recorded(corpus)

    (directory / "content.md").unlink()
    (directory / "figure.png").unlink()
    directory.rmdir()

    restore_deletions(Repository(corpus), changes(corpus))

    assert (directory / "content.md").is_file()
    assert (directory / "figure.png").read_bytes() == b"png"


# ---------------------------------------------------------------------------
# Created
# ---------------------------------------------------------------------------


def test_a_hand_created_file_is_reported(corpus: Path):
    recorded(corpus)
    (corpus / "notes" / "dropped.md").write_text("# Just a file\n", encoding="utf-8")

    reported = changes(corpus)

    assert [change.kind for change in reported] == ["created"]


def test_a_hand_created_file_is_not_adopted(corpus: Path):
    """Guessing metadata for a file someone dropped in would invent exactly
    the identity the rest of the design refuses to invent."""
    (corpus / "notes" / "dropped.md").write_text("# Just a file\n", encoding="utf-8")

    change = changes(corpus)[0]

    assert change.kind == "created"
    assert change.document_id is None
    assert change.owner is None


def test_a_created_file_is_left_on_disk(corpus: Path):
    """Reporting it is the whole job. Deleting someone's file because it has
    no frontmatter would be losing data to enforce tidiness."""
    dropped = corpus / "notes" / "dropped.md"
    dropped.write_text("# Just a file\n", encoding="utf-8")

    restore_deletions(Repository(corpus), changes(corpus))

    assert dropped.is_file()


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_changes_in_every_collection_are_reported(corpus: Path):
    """An index is per collection; a lost document is not. A user who deleted
    something wants to hear about it whichever collection it was in."""
    a_document(corpus, "one.md")
    (corpus / "literature").mkdir(exist_ok=True)
    (corpus / "literature" / "paper.md").write_text(
        "---\nid: bbbbbbbbbb\ntitle: P\nowner: user\n---\n\n# P\n", encoding="utf-8"
    )
    recorded(corpus)

    (corpus / "notes" / "one.md").unlink()
    (corpus / "literature" / "paper.md").unlink()

    assert len(changes(corpus)) == 2


def test_the_index_directory_is_not_reported_as_out_of_band(corpus: Path):
    """kennis writes it itself, every build, and it is not a document."""
    recorded(corpus)
    (corpus / "index").mkdir(exist_ok=True)
    (corpus / "index" / "embeddings.npy").write_bytes(b"\x00" * 32)

    assert changes(corpus) == []


def test_a_document_that_cannot_be_parsed_is_still_reported(corpus: Path):
    """The whole point is to know what was lost, so a document whose
    frontmatter will not parse is reported with an unknown owner rather than
    raising."""
    note = corpus / "notes" / "broken.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\n: : not yaml : :\n---\n\nBody.\n", encoding="utf-8")
    recorded(corpus)
    note.unlink()

    reported = changes(corpus)

    assert [change.kind for change in reported] == ["deleted"]
    assert reported[0].owner is None
