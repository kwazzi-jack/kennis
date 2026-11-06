"""Tags, the engine's part: names, the file, and finding a passage again
(#625, sketch 2026-11-06-tags).

A tag is a flat, free-form name folded to lowercase, with no whitespace or
comma, because those separate tags as they are typed; `/` is an ordinary
character. A passage tag is found again by a quotation of the passage, and
one whose quotation is in no chunk of its document is detached - never
moved to a nearby passage or widened to the document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import KennisError
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import (
    Anchor,
    Detached,
    Placed,
    TagNameRefused,
    Unchecked,
    placed,
    quote_of,
    read_tags,
    split_tag_names,
    tag_name,
    with_tags,
    without_tags,
    written,
)

DOCUMENT = "k3v9x0a2mq"


def a_chunk(number: int, text: str, document: str = DOCUMENT) -> Chunk:
    return Chunk(
        id=f"{document}::{number}",
        collection="literature",
        document_id=document,
        chunk_index=number,
        text=text,
        source_path="literature/a.md",
        char_start=0,
        char_end=len(text),
    )


# ---------------------------------------------------------------------------
# Names


def test_a_name_is_folded_to_lowercase():
    assert tag_name("Calibration") == "calibration"


def test_a_slash_is_an_ordinary_character():
    assert tag_name("thesis/ch3") == "thesis/ch3"


@pytest.mark.parametrize("text", ["", "  ", "phase calibration", "a,b", "a\tb"])
def test_a_name_with_a_separator_or_nothing_is_refused(text: str):
    with pytest.raises(TagNameRefused) as refused:
        tag_name(text)
    assert isinstance(refused.value, KennisError)


def test_names_are_split_at_commas_folded_and_kept_once_in_order():
    assert split_tag_names("Calibration,to-cite,calibration") == (
        "calibration",
        "to-cite",
    )


def test_an_empty_name_between_commas_is_refused():
    with pytest.raises(TagNameRefused):
        split_tag_names("calibration,,to-cite")


# ---------------------------------------------------------------------------
# The file


def test_a_missing_file_holds_no_tags(tmp_path: Path):
    assert read_tags(tmp_path / "tags.yml") == {}


def test_tags_are_written_and_read_back(tmp_path: Path):
    whole = Anchor(DOCUMENT)
    passage = Anchor(DOCUMENT, chunk=12, quote="The gains are solved per scan")
    held = with_tags({}, ("calibration",), whole)
    held = with_tags(held, ("calibration", "to-cite"), passage)
    path = tmp_path / "tags.yml"
    path.write_text(written(held), encoding="utf-8")

    assert read_tags(path) == {
        "calibration": (whole, passage),
        "to-cite": (passage,),
    }


def test_the_file_is_keyed_by_tag_for_a_person_reading_it(tmp_path: Path):
    held = with_tags({}, ("to-cite",), Anchor(DOCUMENT, chunk=3, quote="Gains drift"))

    text = written(held)

    assert text.startswith("to-cite:\n")
    assert "chunk: 3" in text
    assert "quote: Gains drift" in text


def test_a_context_target_is_written_as_a_path(tmp_path: Path):
    held = with_tags({}, ("mine",), Anchor("notes/a b.md", chunk=0, quote="Ours"))

    text = written(held)

    assert "path: notes/a b.md" in text
    assert "document:" not in text
    path = tmp_path / "tags.yml"
    path.write_text(text, encoding="utf-8")
    assert read_tags(path) == held


def test_tagging_twice_changes_nothing():
    anchor = Anchor(DOCUMENT, chunk=1, quote="q")
    once = with_tags({}, ("a",), anchor)

    assert with_tags(once, ("a",), anchor) == once


def test_the_same_passage_found_again_is_one_target():
    """Equal by document and chunk: a fresh quotation of the same chunk is
    not a second target."""
    once = with_tags({}, ("a",), Anchor(DOCUMENT, chunk=1, quote="old words"))

    again = with_tags(once, ("a",), Anchor(DOCUMENT, chunk=1, quote="old words"))

    assert len(again["a"]) == 1


def test_untagging_the_last_target_drops_the_tag():
    anchor = Anchor(DOCUMENT, chunk=1, quote="q")
    held = with_tags(with_tags({}, ("a", "b"), anchor), ("b",), Anchor(DOCUMENT))

    left = without_tags(held, ("a",), Anchor(DOCUMENT, chunk=1))

    assert "a" not in left
    assert left["b"] == (anchor, Anchor(DOCUMENT))


def test_untagging_a_passage_leaves_the_document_s_tag():
    passage = Anchor(DOCUMENT, chunk=1, quote="q")
    held = with_tags(with_tags({}, ("a",), passage), ("a",), Anchor(DOCUMENT))

    left = without_tags(held, ("a",), Anchor(DOCUMENT, chunk=1))

    assert left == {"a": (Anchor(DOCUMENT),)}


def test_a_file_naming_a_tag_twice_is_refused(tmp_path: Path):
    path = tmp_path / "tags.yml"
    path.write_text(
        f"a:\n  - document: {DOCUMENT}\na:\n  - document: other00001\n",
        encoding="utf-8",
    )

    with pytest.raises(KennisError) as refused:
        read_tags(path)
    assert str(path) in str(refused.value)


@pytest.mark.parametrize(
    "text",
    [
        "- just a list\n",
        "a: not a list\n",
        "a:\n  - chunk: 3\n",
        f"a:\n  - document: {DOCUMENT}\n    path: notes/a.md\n",
        f"a:\n  - document: {DOCUMENT}\n    chunk: three\n",
        f"Has Space:\n  - document: {DOCUMENT}\n",
    ],
)
def test_a_file_kennis_cannot_read_is_refused_with_its_path(tmp_path: Path, text: str):
    path = tmp_path / "tags.yml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(KennisError) as refused:
        read_tags(path)
    assert str(path) in str(refused.value)


# ---------------------------------------------------------------------------
# Quoting a passage


def test_a_quote_is_the_passage_s_opening_with_whitespace_collapsed():
    assert quote_of("The  gains\nare solved.") == "The gains are solved."


def test_a_long_quote_is_cut_at_a_word_and_kept_near_eighty_characters():
    text = " ".join(["calibration"] * 30)

    quote = quote_of(text)

    assert 60 <= len(quote) <= 80
    assert text.startswith(quote)
    assert not quote.endswith(" ")
    assert text[len(quote)] == " "


# ---------------------------------------------------------------------------
# Finding a passage again


def test_a_passage_is_placed_in_its_chunk_when_it_is_still_there():
    chunks = [a_chunk(0, "Intro."), a_chunk(1, "The gains are solved per scan.")]
    anchor = Anchor(DOCUMENT, chunk=1, quote="The gains are solved")

    assert placed(anchor, chunks) == Placed(1)


def test_a_passage_that_moved_is_placed_where_its_words_are_now():
    """An edit or a new chunker renumbers chunks; the words decide."""
    chunks = [
        a_chunk(0, "Intro."),
        a_chunk(1, "A new section."),
        a_chunk(2, "Before. The gains are solved per scan."),
    ]
    anchor = Anchor(DOCUMENT, chunk=1, quote="The gains are solved")

    assert placed(anchor, chunks) == Placed(2)


def test_words_that_occur_twice_are_placed_nearest_the_hint():
    chunks = [a_chunk(number, "The gains are solved.") for number in range(6)]
    anchor = Anchor(DOCUMENT, chunk=4, quote="The gains are solved")
    moved = [chunk for chunk in chunks if chunk.chunk_index != 4]

    assert placed(anchor, moved) in (Placed(3), Placed(5))


def test_a_quote_split_across_whitespace_is_still_found():
    chunks = [a_chunk(0, "The gains\n  are solved per scan.")]

    assert placed(Anchor(DOCUMENT, chunk=0, quote="The gains are solved"), chunks) == (
        Placed(0)
    )


def test_a_passage_whose_words_are_gone_is_detached_not_moved():
    chunks = [a_chunk(0, "Intro."), a_chunk(1, "Something else entirely.")]
    anchor = Anchor(DOCUMENT, chunk=1, quote="The gains are solved")

    assert placed(anchor, chunks) == Detached()


def test_another_document_s_words_do_not_place_a_passage():
    chunks = [
        a_chunk(0, "Intro."),
        a_chunk(0, "The gains are solved.", document="other00001"),
    ]

    assert placed(Anchor(DOCUMENT, chunk=0, quote="The gains are solved"), chunks) == (
        Detached()
    )


def test_a_document_the_index_does_not_hold_is_unchecked_not_detached():
    """A stale or missing index says nothing about the text."""
    chunks = [a_chunk(0, "The gains are solved.", document="other00001")]

    assert placed(Anchor(DOCUMENT, chunk=0, quote="The gains"), chunks) == Unchecked()
    assert placed(Anchor(DOCUMENT), chunks) == Unchecked()


def test_a_whole_document_is_placed_while_the_index_holds_it():
    assert placed(Anchor(DOCUMENT), [a_chunk(0, "Intro.")]) == Placed(None)
