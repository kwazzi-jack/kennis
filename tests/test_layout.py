"""The directory rules: what is a document, what is a group, what is neither.

A document is told from a user-created group by filesystem shape alone - no
metadata field and no reserved bucket name - so these are the tests that keep
the shape rule honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.corpus.layout import (
    WRAPPED_DOCUMENT_FILENAME,
    classify_child,
    collection_root,
    default_corpus_root,
    iter_documents,
    title_filename,
    title_needs_dot_stripped,
    unique_filename,
)
from kennis.engine.errors import UnknownCollection

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_a_markdown_file_is_a_document(tmp_path: Path):
    (tmp_path / "A note.md").write_text("x", encoding="utf-8")

    assert classify_child(tmp_path / "A note.md") == "leaf-bare"


def test_a_directory_holding_content_md_is_a_document_with_assets(tmp_path: Path):
    wrapper = tmp_path / "A paper"
    wrapper.mkdir()
    (wrapper / WRAPPED_DOCUMENT_FILENAME).write_text("x", encoding="utf-8")

    assert classify_child(wrapper) == "leaf-wrapped"


def test_any_other_directory_is_a_group(tmp_path: Path):
    (tmp_path / "Reading").mkdir()

    assert classify_child(tmp_path / "Reading") == "group"


def test_a_non_markdown_file_is_neither(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        classify_child(tmp_path / "notes.txt")


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def test_the_walk_descends_through_groups_to_any_depth(tmp_path: Path):
    deep = tmp_path / "Reading" / "2026" / "March"
    deep.mkdir(parents=True)
    (deep / "A note.md").write_text("x", encoding="utf-8")

    found = list(iter_documents(tmp_path))

    assert [location.md_path for location in found] == [deep / "A note.md"]


def test_the_walk_does_not_descend_into_a_wrapped_document(tmp_path: Path):
    """Its assets are part of the document, not documents of their own."""
    wrapper = tmp_path / "A paper"
    wrapper.mkdir()
    (wrapper / WRAPPED_DOCUMENT_FILENAME).write_text("x", encoding="utf-8")
    (wrapper / "appendix.md").write_text("x", encoding="utf-8")

    found = list(iter_documents(tmp_path))

    assert len(found) == 1
    assert found[0].wrapper_dir == wrapper


def test_the_walk_yields_nothing_for_a_root_that_does_not_exist(tmp_path: Path):
    """A fresh machine with nothing fetched, which is a normal state."""
    assert list(iter_documents(tmp_path / "absent")) == []


def test_the_walk_is_ordered(tmp_path: Path):
    for name in ("C.md", "A.md", "B.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    found = [location.md_path.name for location in iter_documents(tmp_path)]

    assert found == ["A.md", "B.md", "C.md"]


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------


def test_a_filename_is_the_title_verbatim():
    """Not lowercased or hyphenated: nothing parses this filename as a key,
    because the surrogate identifier is what every handle addresses."""
    assert title_filename("On the Origin of Radio Sources") == (
        "On the Origin of Radio Sources.md"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("A/B", "AB.md"),
        ('Quote "this"', "Quote this.md"),
        ("Spaced    out", "Spaced out.md"),
        ("   padded   ", "padded.md"),
        ("", "untitled.md"),
        ("///", "untitled.md"),
    ],
)
def test_a_filename_survives_an_awkward_title(title: str, expected: str):
    assert title_filename(title) == expected


def test_a_leading_dot_is_stripped():
    """Any dot-prefixed name is corpus bookkeeping rather than a document, so
    an unstripped one would write successfully and then be permanently
    invisible to every future walk."""
    assert title_filename(".bashrc") == "bashrc.md"
    assert title_needs_dot_stripped(".bashrc") is True
    assert title_needs_dot_stripped("bashrc") is False


def test_an_unused_filename_is_taken_as_it_is():
    assert unique_filename("A note.md", set()) == "A note.md"


def test_a_taken_filename_is_suffixed():
    taken = {"A note.md", "A note (2).md"}

    assert unique_filename("A note.md", taken) == "A note (3).md"


def test_content_md_is_always_treated_as_taken():
    """A bare document claiming that exact name would make its own parent
    directory classify as a wrapped document, hiding every sibling in it."""
    assert unique_filename(WRAPPED_DOCUMENT_FILENAME, set()) == "content (2).md"


# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------


def test_a_collection_lives_under_the_corpus_root(tmp_path: Path):
    assert collection_root(tmp_path, "literature") == tmp_path / "literature"


def test_an_unknown_collection_has_no_root(tmp_path: Path):
    with pytest.raises(UnknownCollection):
        collection_root(tmp_path, "papers")


def test_the_default_corpus_root_is_machine_global():
    """A paper read for one project is the same paper in the next, so the
    corpus is not per-project."""
    assert default_corpus_root().name == "kennis"
    assert default_corpus_root().is_absolute()
