"""Reading and writing one document, and the shape it takes on disk.

The plan's list for this milestone is behaviour, not structure, so these
assert what a caller observes: what goes in comes back out, an identifier
survives everything that is not a deletion, and an interrupt leaves one whole
document rather than half of two.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

import pytest

from kennis.engine.corpus.document import (
    Document,
    move_document,
    read_document,
    remove_document,
    write_document,
)
from kennis.engine.corpus.layout import WRAPPED_DOCUMENT_FILENAME
from kennis.engine.corpus.schema import LiteratureFrontmatter, NoteFrontmatter
from kennis.engine.errors import DocumentInvalid

BODY = "# A paper\n\nThe first paragraph, with a [1] citation in it.\n"


def a_note_frontmatter(**overrides: Any) -> NoteFrontmatter:
    fields: dict[str, Any] = {
        "id": "abcdefghij",
        "title": "A note",
        "owner": "user",
        "source": {"from": "path:/tmp/a.md", "via": "verbatim", "format": "markdown"},
    }
    fields.update(overrides)
    return NoteFrontmatter.model_validate(fields)


def a_paper_frontmatter(**overrides: Any) -> LiteratureFrontmatter:
    fields: dict[str, Any] = {
        "id": "zyxwvutsrq",
        "title": "A paper",
        "owner": "user",
        "id_from": "arxiv:1101.1764",
        "source": {"from": "arxiv:1101.1764", "via": "arxiv-html", "format": "html"},
        "bib": {
            "citekey": "welman2024",
            "arxiv_id": "1101.1764",
            "doi": "10.1088/0004-637X/1",
        },
    }
    fields.update(overrides)
    return LiteratureFrontmatter.model_validate(fields)


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_a_document_written_and_read_back_is_unchanged(tmp_path: Path):
    frontmatter = a_paper_frontmatter()

    write_document(tmp_path / "A paper.md", frontmatter=frontmatter, body=BODY)
    read_back = read_document(tmp_path / "A paper.md", collection="literature")

    assert read_back.frontmatter == frontmatter
    assert read_back.body == BODY
    assert read_back.id == frontmatter.id


def test_a_document_with_assets_is_written_inside_a_wrapper(tmp_path: Path):
    """A `.md` file is a document; a directory holding `content.md` is a
    document with assets. The caller names the bare path either way."""
    written = write_document(
        tmp_path / "A paper.md",
        frontmatter=a_paper_frontmatter(),
        body=BODY,
        assets={"figure-1.png": b"\x89PNG"},
    )

    assert written.wrapper_dir == tmp_path / "A paper"
    assert written.md_path == tmp_path / "A paper" / WRAPPED_DOCUMENT_FILENAME
    assert (tmp_path / "A paper" / "figure-1.png").read_bytes() == b"\x89PNG"


def test_a_wrapped_document_reads_back_knowing_it_is_wrapped(tmp_path: Path):
    written = write_document(
        tmp_path / "A paper.md",
        frontmatter=a_paper_frontmatter(),
        body=BODY,
        assets={"figure-1.png": b"\x89PNG"},
    )

    read_back = read_document(written.md_path, collection="literature")

    assert read_back.wrapper_dir == tmp_path / "A paper"


def test_the_body_survives_trailing_whitespace_and_blank_lines(tmp_path: Path):
    body = "First.\n\n\nLast line, no newline after it."

    write_document(tmp_path / "A note.md", frontmatter=a_note_frontmatter(), body=body)

    assert read_document(tmp_path / "A note.md", collection="notes").body == body


# ---------------------------------------------------------------------------
# The identifier survives everything but deletion
# ---------------------------------------------------------------------------


def test_editing_the_body_does_not_change_the_identifier(tmp_path: Path):
    """The identifier is derived from identity, never from content."""
    path = tmp_path / "A paper.md"
    write_document(path, frontmatter=a_paper_frontmatter(), body=BODY)
    before = read_document(path, collection="literature")

    write_document(path, frontmatter=before.frontmatter, body=BODY + "\nMore.\n")
    after = read_document(path, collection="literature")

    assert after.id == before.id
    assert after.body != before.body


def test_retitling_a_document_does_not_change_its_identifier(tmp_path: Path):
    """What the surrogate buys: the filename and the title are both free to
    change, and every handle pointing at the document stays valid."""
    write_document(
        tmp_path / "A paper.md", frontmatter=a_paper_frontmatter(), body=BODY
    )
    document = read_document(tmp_path / "A paper.md", collection="literature")

    moved = move_document(
        document,
        target_md_path=tmp_path / "A rather better title.md",
        updates={"title": "A rather better title"},
    )

    assert moved.id == document.id
    assert moved.frontmatter.title == "A rather better title"
    assert not (tmp_path / "A paper.md").exists()


def test_a_move_carries_the_assets_with_it(tmp_path: Path):
    written = write_document(
        tmp_path / "A paper.md",
        frontmatter=a_paper_frontmatter(),
        body=BODY,
        assets={"figure-1.png": b"\x89PNG"},
    )

    moved = move_document(written, target_md_path=tmp_path / "group" / "A paper.md")

    assert (tmp_path / "group" / "A paper" / "figure-1.png").read_bytes() == b"\x89PNG"
    assert moved.wrapper_dir == tmp_path / "group" / "A paper"
    assert not (tmp_path / "A paper").exists()


def test_a_move_may_not_change_the_identifier(tmp_path: Path):
    write_document(
        tmp_path / "A paper.md", frontmatter=a_paper_frontmatter(), body=BODY
    )
    document = read_document(tmp_path / "A paper.md", collection="literature")

    with pytest.raises(ValueError):
        move_document(
            document, target_md_path=tmp_path / "B.md", updates={"id": "0000000000"}
        )


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def test_removing_a_bare_document_removes_the_file(tmp_path: Path):
    written = write_document(
        tmp_path / "A note.md", frontmatter=a_note_frontmatter(), body=BODY
    )

    remove_document(written)

    assert not (tmp_path / "A note.md").exists()


def test_removing_a_wrapped_document_removes_its_assets_too(tmp_path: Path):
    written = write_document(
        tmp_path / "A paper.md",
        frontmatter=a_paper_frontmatter(),
        body=BODY,
        assets={"figure-1.png": b"\x89PNG"},
    )

    remove_document(written)

    assert not (tmp_path / "A paper").exists()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unrecognised_owner_is_refused_naming_the_document(tmp_path: Path):
    """A document carrying the old `managed_by: boepie`, or an `owner` kennis
    does not recognise, is refused with the document named."""
    path = tmp_path / "A note.md"
    path.write_text(
        "---\n"
        "id: abcdefghij\n"
        "title: A note\n"
        "owner: boepie\n"
        "source:\n"
        "  from: 'path:/tmp/a.md'\n"
        "  via: verbatim\n"
        "  format: markdown\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentInvalid) as raised:
        read_document(path, collection="notes")

    assert str(path) in str(raised.value)
    assert raised.value.resolution


def test_a_document_with_no_frontmatter_at_all_is_refused(tmp_path: Path):
    path = tmp_path / "A note.md"
    path.write_text("just a body, no frontmatter\n", encoding="utf-8")

    with pytest.raises(DocumentInvalid):
        read_document(path, collection="notes")


def test_a_document_with_no_identifier_is_refused(tmp_path: Path):
    path = tmp_path / "A note.md"
    path.write_text("---\ntitle: A note\nowner: user\n---\n\nbody\n", encoding="utf-8")

    with pytest.raises(DocumentInvalid):
        read_document(path, collection="notes")


def test_writing_over_a_different_document_is_refused(tmp_path: Path):
    """A wrapper directory's name is title-derived, so two unrelated documents
    can want the same one. A same-identifier write is a legitimate update; a
    different one is not."""
    write_document(
        tmp_path / "A paper.md",
        frontmatter=a_paper_frontmatter(),
        body=BODY,
        assets={"figure-1.png": b"\x89PNG"},
    )

    with pytest.raises(ValueError):
        write_document(
            tmp_path / "A paper.md",
            frontmatter=a_paper_frontmatter(id="0000000000"),
            body=BODY,
            assets={"figure-2.png": b"\x89PNG"},
        )


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


def test_an_interrupted_write_leaves_the_old_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A reader sees either the old content or the new one, never a
    truncation. `BaseException` rather than `Exception` because a Ctrl-C
    partway through the write is the case this exists for."""
    path = tmp_path / "A paper.md"
    write_document(path, frontmatter=a_paper_frontmatter(), body=BODY)
    original_bytes = path.read_bytes()

    def interrupted(*arguments: object, **keywords: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)

    with pytest.raises(KeyboardInterrupt):
        write_document(
            path, frontmatter=a_paper_frontmatter(), body="something completely new"
        )

    assert path.read_bytes() == original_bytes


def test_an_interrupted_write_leaves_no_debris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "A paper.md"
    write_document(path, frontmatter=a_paper_frontmatter(), body=BODY)

    def interrupted(*arguments: object, **keywords: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        write_document(path, frontmatter=a_paper_frontmatter(), body="new")

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["A paper.md"]


def test_a_write_that_never_completed_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The same property for a document that did not exist yet: either the new
    one is there whole, or nothing is."""

    def interrupted(*arguments: object, **keywords: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)

    with pytest.raises(KeyboardInterrupt):
        write_document(
            tmp_path / "A note.md", frontmatter=a_note_frontmatter(), body=BODY
        )

    assert list(tmp_path.iterdir()) == []


def test_a_document_is_a_frozen_record(tmp_path: Path):
    written = write_document(
        tmp_path / "A note.md", frontmatter=a_note_frontmatter(), body=BODY
    )

    assert isinstance(written, Document)
    with pytest.raises(dataclasses.FrozenInstanceError):
        written.body = "reassigned"
