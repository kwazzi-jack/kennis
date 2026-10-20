"""What kennis obtained is read-only; what the person wrote keeps its id (14g, #514).

A pack's files in the store, the notes a pack owns in the corpus and fetched
documentation pages are written without write permission, so an editor
says so before a person changes text kennis will put back. Literature is
the agreed exception: a paper's text may be corrected in place. Read-only
is a signal, not a protection - the protection is a sync comparing a file
with its source - so every way kennis itself replaces or removes such a
file has to work on one, on every platform: Windows refuses to replace or
delete a read-only file.

A person who wants their own version makes one: `kennis corpus copy`
writes a new note of theirs recording what it came from, and a pack note
found edited at a sync is copied out the same way before the pack's text
is put back, so no edit is lost.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.corpus.add import AddOptions, add_docs
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.sync import sync_corpus
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.installed import remove_pack
from kennis.engine.pack.store import install_pack, pack_root
from kennis.engine.pack.update import update_pack
from test_add_docs import BASE, sphinx_site


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return root


@pytest.fixture(autouse=True)
def refusing_as_windows_does(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Windows refuses to replace or delete a read-only file; POSIX asks
    only whether the directory is writable. So on Linux every step kennis
    takes to make a file writable before replacing or removing it is inert,
    and an injection removing one passes. Under this fixture the two calls
    every such path ends in refuse as Windows would, here too."""
    real_replace = os.replace
    real_unlink = os.unlink

    def is_read_only_at(path: str | Path, dir_fd: int | None) -> bool:
        try:
            mode = os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return False
        return stat.S_ISREG(mode) and not mode & stat.S_IWRITE

    def replace(source: str | Path, target: str | Path) -> None:
        if is_read_only_at(target, None):
            raise PermissionError(13, "read-only, as Windows refuses", str(target))
        real_replace(source, target)

    def unlink(path: str | Path, *, dir_fd: int | None = None) -> None:
        if is_read_only_at(path, dir_fd):
            raise PermissionError(13, "read-only, as Windows refuses", str(path))
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "remove", unlink)
    yield


def test_the_fixture_refuses_what_windows_refuses(tmp_path: Path):
    """Without this the tests below would pass on Linux for the reason
    they exist to rule out."""
    target = tmp_path / "sealed.md"
    target.write_text("x", encoding="utf-8")
    target.chmod(0o444)
    with pytest.raises(PermissionError):
        target.unlink()
    with pytest.raises(PermissionError):
        shutil.rmtree(tmp_path)
    source = tmp_path / "new.md"
    source.write_text("y", encoding="utf-8")
    with pytest.raises(PermissionError):
        os.replace(source, target)


def a_pack(root: Path, files: dict[str, str] | None = None) -> Path:
    if root.exists():
        shutil.rmtree(root)
    for relative, text in (files or {"notes/one.md": "One.\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    path = root / "alpha.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
        "corpus:\n  notes:\n    - source: notes/\n",
        encoding="utf-8",
    )
    update_pack(path)
    return path


def installed(
    corpus: Path, tmp_path: Path, files: dict[str, str] | None = None
) -> None:
    install_pack(corpus, a_pack(tmp_path / "alpha", files))


def is_read_only(path: Path) -> bool:
    """By the mode bit, which Python maps from the read-only attribute on
    Windows; `os.access` would answer yes for an administrator anyway."""
    return not path.stat().st_mode & stat.S_IWRITE


def edited_by_hand(path: Path, old: str, new: str) -> None:
    """What an editor's "save anyway" does: make the file writable, then
    write."""
    path.chmod(path.stat().st_mode | stat.S_IWRITE)
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), "utf-8")


def notes_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="notes").contents().documents)


def the_pack_s_note(corpus: Path) -> Document:
    (note,) = [one for one in notes_in(corpus) if one.frontmatter.owner != "user"]
    return note


# ---------------------------------------------------------------------------
# What is read-only, and what is not


def test_a_pack_s_files_in_the_store_are_read_only(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)

    files = [
        path
        for path in pack_root(corpus, "alpha").rglob("*")
        # `state.json` is kennis's own record of the install, not obtained.
        if path.is_file() and path.name != "state.json"
    ]

    assert len(files) == 2
    assert all(is_read_only(path) for path in files)


def test_a_note_a_pack_owns_is_read_only(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)

    assert is_read_only(the_pack_s_note(corpus).md_path)


def test_a_fetched_documentation_page_is_read_only(corpus: Path):
    docs = Collection(root=corpus, name="docs")
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    pages = docs.contents().documents
    assert pages
    assert all(is_read_only(page.md_path) for page in pages)


def test_the_person_s_note_is_not_read_only(corpus: Path):
    answered = CliRunner().invoke(main, ["remember", "--no-index", "Mine."])
    assert answered.exit_code == 0, answered.output

    (note,) = notes_in(corpus)
    assert not is_read_only(note.md_path)


# ---------------------------------------------------------------------------
# kennis can still replace and remove what it made read-only


def test_a_new_release_replaces_the_read_only_store(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)

    installed(corpus, tmp_path, files={"notes/two.md": "Two.\n"})

    names = {path.name for path in pack_root(corpus, "alpha").rglob("*.md")}
    assert names == {"two.md"}


def test_removing_a_pack_removes_its_read_only_store(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)

    remove_pack(corpus, "alpha")

    assert not pack_root(corpus, "alpha").exists()


def test_a_sync_rewrites_a_read_only_note_when_the_pack_changes(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)

    installed(corpus, tmp_path, files={"notes/one.md": "Second.\n"})
    sync_corpus(corpus)

    note = the_pack_s_note(corpus)
    assert note.body == "Second.\n"
    assert is_read_only(note.md_path)


def test_a_sync_removes_a_read_only_note_the_pack_dropped(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)

    installed(corpus, tmp_path, files={"notes/two.md": "Two.\n"})
    sync_corpus(corpus)

    assert [note.body for note in notes_in(corpus)] == ["Two.\n"]


def test_a_read_only_note_can_be_moved(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    original = the_pack_s_note(corpus)

    answered = CliRunner().invoke(
        main, ["corpus", "move", original.id, "--group", "elsewhere"]
    )

    assert answered.exit_code == 0, answered.output
    moved = the_pack_s_note(corpus)
    assert moved.md_path.parent.name == "elsewhere"
    assert not original.md_path.exists()
    assert is_read_only(moved.md_path)


def test_a_read_only_page_can_be_removed(corpus: Path):
    docs = Collection(root=corpus, name="docs")
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )
    page = docs.contents().documents[0]

    docs.remove(page)

    assert not page.md_path.exists()


# ---------------------------------------------------------------------------
# An edit to a pack's note is kept as the person's own


def test_an_edited_pack_note_is_copied_out_and_the_pack_s_text_put_back(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    original = the_pack_s_note(corpus)
    edited_by_hand(original.md_path, "First.", "Mine now.")

    result = sync_corpus(corpus)

    restored = the_pack_s_note(corpus)
    assert restored.id == original.id
    assert restored.body == "First.\n"
    assert is_read_only(restored.md_path)
    (mine,) = [one for one in notes_in(corpus) if one.frontmatter.owner == "user"]
    assert mine.body == "Mine now.\n"
    assert mine.id != original.id
    assert mine.frontmatter.source.via == "copy"
    assert mine.frontmatter.source.origin == f"copy:{original.id}"
    assert result.copied == ((original.id, mine.id),)


def test_the_person_s_copy_is_left_alone_by_the_next_sync(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    edited_by_hand(the_pack_s_note(corpus).md_path, "First.", "Mine now.")
    sync_corpus(corpus)

    again = sync_corpus(corpus)

    assert again.copied == ()
    assert len(notes_in(corpus)) == 2


def test_an_edited_note_the_pack_dropped_is_copied_out_before_it_goes(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    edited_by_hand(the_pack_s_note(corpus).md_path, "First.", "Mine now.")

    installed(corpus, tmp_path, files={"notes/two.md": "Two.\n"})
    sync_corpus(corpus)

    bodies = sorted(note.body for note in notes_in(corpus))
    assert bodies == ["Mine now.\n", "Two.\n"]


# ---------------------------------------------------------------------------
# Making one's own version


def test_corpus_copy_makes_a_note_of_the_person_s_from_any_document(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    original = the_pack_s_note(corpus)

    answered = CliRunner().invoke(main, ["corpus", "copy", original.id])

    assert answered.exit_code == 0, answered.output
    (mine,) = [one for one in notes_in(corpus) if one.frontmatter.owner == "user"]
    assert mine.body == original.body
    assert mine.frontmatter.title == original.frontmatter.title
    assert mine.frontmatter.source.origin == f"copy:{original.id}"
    assert not is_read_only(mine.md_path)
    assert mine.id in answered.output
    unchanged = the_pack_s_note(corpus)
    assert unchanged.md_path.read_bytes() == original.md_path.read_bytes()


def test_claim_and_disown_are_gone(corpus: Path):
    for command in ("claim", "disown"):
        answered = CliRunner().invoke(main, ["corpus", command, "x"])
        assert answered.exit_code != 0
        assert "No such command" in answered.output


# ---------------------------------------------------------------------------
# After git writes the file again


def test_a_pack_note_restored_after_a_hand_deletion_is_read_only_again(
    corpus: Path, tmp_path: Path
):
    """git records no write permission, so a file it checks out is
    writable; the next write through kennis restores a hand deletion."""
    installed(corpus, tmp_path)
    assert CliRunner().invoke(main, ["corpus", "sync"]).exit_code == 0
    note = the_pack_s_note(corpus)
    note.md_path.chmod(note.md_path.stat().st_mode | stat.S_IWRITE)
    note.md_path.unlink()

    answered = CliRunner().invoke(main, ["remember", "--no-index", "Mine."])

    assert answered.exit_code == 0, answered.output
    assert note.md_path.exists()
    assert is_read_only(note.md_path)
