"""Annotations, the engine's part: tag names, the store, and finding a
selection again (#625, #50; sketch 2026-11-16-annotations).

An annotation is a selection of a document's text - or the whole document
- with tags and an optional comment. A selection is found again by its
words, with its offsets as a hint; one whose words are nowhere in its
document is detached, never moved to a neighbour or widened to the
document.
"""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from kennis.engine.annotations import (
    Annotation,
    AnnotationStore,
    Detached,
    Placed,
    Selector,
    Span,
    Unchecked,
    admitting,
    chunk_at,
    indexed_text,
    located,
    own_end,
    placed,
    read_annotations,
    rehinted,
    selector_of,
    tags_on,
    with_tags,
    without_tags,
    written,
)
from kennis.engine.errors import KennisError
from kennis.engine.rag.models import Chunk
from kennis.engine.tags import TagNameRefused, split_tag_names, tag_name

DOCUMENT = "k3v9x0a2mq"

BODY = (
    "# Calibration\n\n"
    "The gains are solved per scan and per antenna.\n\n"
    "A second paragraph says the gains drift slowly.\n\n"
    "The gains are solved per scan and per antenna.\n"
)


def chunks_of(text: str, cuts: list[int], document: str = DOCUMENT) -> list[Chunk]:
    """`text` cut at `cuts` into chunks, as the chunker lays them."""
    bounds = [0, *cuts, len(text)]
    return [
        Chunk(
            id=f"{document}::{number}",
            collection="literature",
            document_id=document,
            chunk_index=number,
            text=text[start:end],
            source_path="literature/a.md",
            char_start=start,
            char_end=end,
        )
        for number, (start, end) in enumerate(pairwise(bounds))
    ]


def an_annotation(
    selector: Selector | None,
    tags: tuple[str, ...] = ("a",),
    *,
    identifier: str = "0000000a",
    document: str = DOCUMENT,
    comment: str | None = None,
) -> Annotation:
    return Annotation(
        id=identifier,
        document=document,
        selector=selector,
        tags=tags,
        comment=comment,
        created="2026-11-16T10:00:00+00:00",
    )


def selecting(text: str, words: str, occurrence: int = 0) -> Selector:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(words, start + 1)
    return selector_of(text, start, start + len(words))


# ---------------------------------------------------------------------------
# Names


def test_a_name_is_folded_to_lowercase() -> None:
    assert tag_name("Calibration") == "calibration"


def test_a_slash_is_an_ordinary_character() -> None:
    assert tag_name("thesis/ch3") == "thesis/ch3"


@pytest.mark.parametrize("text", ["", "  ", "phase calibration", "a,b", "a\tb"])
def test_a_name_with_a_separator_or_nothing_is_refused(text: str) -> None:
    with pytest.raises(TagNameRefused) as refused:
        tag_name(text)
    assert isinstance(refused.value, KennisError)


def test_names_are_split_at_commas_folded_and_kept_once_in_order() -> None:
    assert split_tag_names("Calibration,to-cite,calibration") == (
        "calibration",
        "to-cite",
    )


def test_an_empty_name_between_commas_is_refused() -> None:
    with pytest.raises(TagNameRefused):
        split_tag_names("calibration,,to-cite")


# ---------------------------------------------------------------------------
# The store


def test_a_missing_file_holds_nothing(tmp_path: Path) -> None:
    assert read_annotations(tmp_path / "annotations.json") == AnnotationStore()


def test_annotations_are_written_and_read_back(tmp_path: Path) -> None:
    store = AnnotationStore(
        (
            an_annotation(None, ("calibration",), identifier="0000000a"),
            an_annotation(
                selecting(BODY, "gains drift slowly"),
                ("calibration", "to-cite"),
                identifier="0000000b",
                comment="Same prior as in section 3.",
            ),
        ),
        {"to-cite": "red"},
    )
    path = tmp_path / "annotations.json"
    path.write_text(written(store), encoding="utf-8")

    assert read_annotations(path) == store


def test_the_file_is_ascii_and_keeps_an_accent(tmp_path: Path) -> None:
    """The ASCII rule holds for what kennis writes, and an accent in a
    selection or a comment survives as an escape."""
    body = "Le r\u00e9sum\u00e9 de Smirnov."
    store = AnnotationStore(
        (an_annotation(selecting(body, "r\u00e9sum\u00e9"), comment="d\u00e9j\u00e0"),)
    )
    text = written(store)
    path = tmp_path / "annotations.json"
    path.write_text(text, encoding="utf-8")

    assert text.isascii()
    assert read_annotations(path) == store


def test_an_annotation_with_no_tag_and_no_comment_is_not_kept() -> None:
    store = AnnotationStore((an_annotation(None, ()),))

    assert written(store) == ""


def test_a_colour_of_a_tag_nothing_carries_is_not_kept(tmp_path: Path) -> None:
    store = AnnotationStore((an_annotation(None, ("a",)),), {"a": "red", "b": "blue"})

    assert json.loads(written(store))["colours"] == {"a": "red"}


@pytest.mark.parametrize(
    "document",
    [
        "not json at all",
        '{"annotations": []}',
        '{"format": 2, "annotations": []}',
        '{"format": 1, "annotations": [{"id": "0000000a", "created": "x"}]}',
        '{"format": 1, "annotations": [{"id": "x", "document": "d", "created": "x"}]}',
        '{"format": 1, "annotations": [{"id": "0000000a", "document": "d", '
        '"tags": ["Has Space"], "created": "x"}]}',
        '{"format": 1, "annotations": [{"id": "0000000a", "document": "d", '
        '"tags": ["A"], "created": "x"}]}',
        '{"format": 1, "annotations": [{"id": "0000000a", "document": "d", '
        '"created": "x", "colour": "red"}]}',
        '{"format": 1, "annotations": [], "colours": {"a": "mauve"}}',
    ],
)
def test_a_file_kennis_cannot_read_is_refused_with_its_path(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "annotations.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(KennisError) as refused:
        read_annotations(path)
    assert str(path) in str(refused.value)


def test_an_id_used_twice_is_refused(tmp_path: Path) -> None:
    store = AnnotationStore((an_annotation(None), an_annotation(None, ("b",))))
    path = tmp_path / "annotations.json"
    path.write_text(written(store), encoding="utf-8")

    with pytest.raises(KennisError, match="used twice"):
        read_annotations(path)


# ---------------------------------------------------------------------------
# Changing


def test_tagging_a_selection_makes_one_annotation_carrying_every_name() -> None:
    selector = selecting(BODY, "gains drift slowly")

    store, added = with_tags(AnnotationStore(), DOCUMENT, selector, ("b", "a"))

    assert added == ("b", "a")
    assert len(store.annotations) == 1
    assert store.annotations[0].tags == ("a", "b")


def test_tagging_the_same_selection_again_adds_to_its_annotation() -> None:
    selector = selecting(BODY, "gains drift slowly")
    once, _ = with_tags(AnnotationStore(), DOCUMENT, selector, ("a",))

    again, added = with_tags(once, DOCUMENT, selector, ("a", "b"))

    assert added == ("b",)
    assert len(again.annotations) == 1
    assert again.annotations[0].tags == ("a", "b")


def test_tagging_twice_changes_nothing() -> None:
    selector = selecting(BODY, "gains drift slowly")
    once, _ = with_tags(AnnotationStore(), DOCUMENT, selector, ("a",))

    again, added = with_tags(once, DOCUMENT, selector, ("a",))

    assert added == ()
    assert again == once


def test_the_whole_document_and_a_selection_are_two_annotations() -> None:
    store, _ = with_tags(AnnotationStore(), DOCUMENT, None, ("a",))
    store, _ = with_tags(store, DOCUMENT, selecting(BODY, "gains drift"), ("a",))

    assert [each.selector is None for each in store.annotations] == [True, False]


def test_untagging_the_last_name_drops_the_annotation() -> None:
    store, _ = with_tags(AnnotationStore(), DOCUMENT, None, ("a",))
    chosen = [store.annotations[0].id]

    left, removed = without_tags(store, chosen, ("a",))

    assert removed == ("a",)
    assert left.annotations == ()


def test_untagging_keeps_an_annotation_that_has_a_comment() -> None:
    store = AnnotationStore((an_annotation(None, ("a",), comment="Keep me."),))

    left, _ = without_tags(store, ["0000000a"], ("a",))

    assert left.annotations[0].tags == ()
    assert left.annotations[0].comment == "Keep me."


def test_untagging_touches_only_the_annotations_chosen() -> None:
    store = AnnotationStore(
        (
            an_annotation(None, ("a",), identifier="0000000a"),
            an_annotation(None, ("a",), identifier="0000000b"),
        )
    )

    left, _ = without_tags(store, ["0000000b"], ("a",))

    assert [each.id for each in left.annotations] == ["0000000a"]


def test_a_selection_of_no_words_is_refused() -> None:
    with pytest.raises(ValueError, match="no words"):
        selector_of("a   b", 1, 4)


# ---------------------------------------------------------------------------
# Finding a selection again


def test_a_selection_is_found_where_its_hint_says() -> None:
    selector = selecting(BODY, "gains drift slowly")

    assert located(selector, BODY) == Span(selector.start, selector.end)


def test_a_selection_that_moved_is_found_where_its_words_are_now() -> None:
    selector = selecting(BODY, "gains drift slowly")
    edited = "A new opening paragraph, inserted.\n\n" + BODY

    span = located(selector, edited)

    assert span is not None
    assert edited[span.start : span.end] == "gains drift slowly"


def test_a_selection_split_across_new_whitespace_is_still_found() -> None:
    selector = selecting(BODY, "gains drift slowly")
    edited = BODY.replace("gains drift slowly", "gains\ndrift   slowly")

    span = located(selector, edited)

    assert span is not None
    assert edited[span.start : span.end] == "gains\ndrift   slowly"


def test_repeated_words_are_told_apart_by_their_surroundings() -> None:
    """The sentence occurs twice; the second is selected. Text inserted
    between them moves the second further from its hint than the first,
    and the prefix still picks the second."""
    selector = selecting(BODY, "The gains are solved per scan", occurrence=1)
    edited = BODY.replace(
        "A second paragraph", "A much longer second paragraph " + "x " * 200
    )

    span = located(selector, edited)

    assert span is not None
    assert span.start == edited.rindex("The gains are solved per scan")


def test_repeated_words_with_equal_surroundings_go_to_the_nearest() -> None:
    text = "one two. one two. one two."
    selector = Selector("one two", "", "", 9, 16)

    assert located(selector, text.replace("one two", "one  two")) == Span(10, 18)


def test_a_selection_whose_words_are_gone_is_not_found() -> None:
    selector = selecting(BODY, "gains drift slowly")

    assert located(selector, BODY.replace("drift", "wander")) is None


def test_the_indexed_text_is_the_body_with_blank_gaps_as_spaces() -> None:
    chunks = chunks_of(BODY, [15, 63])
    without_gap = [chunks[0], chunks[2]]

    assert indexed_text(chunks) == BODY
    rebuilt = indexed_text(without_gap)
    assert rebuilt[:15] == BODY[:15]
    assert rebuilt[63:] == BODY[63:]
    assert rebuilt[15:63].strip() == ""


def test_a_selection_is_placed_in_the_chunk_it_begins_in() -> None:
    chunks = chunks_of(BODY, [15, 63, 112])
    annotation = an_annotation(selecting(BODY, "gains drift slowly"))

    where = placed(annotation, chunks)

    assert isinstance(where, Placed)
    assert where.chunk == 2


def test_a_selection_whose_words_are_gone_is_detached_not_moved() -> None:
    chunks = chunks_of(BODY.replace("drift", "wander"), [15, 63])
    annotation = an_annotation(selecting(BODY, "gains drift slowly"))

    assert placed(annotation, chunks) == Detached()


def test_another_document_s_words_do_not_place_a_selection() -> None:
    chunks = chunks_of(BODY, [15], document="other00001") + chunks_of("Nothing", [])
    annotation = an_annotation(selecting(BODY, "gains drift slowly"))

    assert placed(annotation, chunks) == Detached()


def test_a_document_the_index_does_not_hold_is_unchecked() -> None:
    annotation = an_annotation(selecting(BODY, "gains drift slowly"))

    assert placed(annotation, chunks_of(BODY, [], document="other00001")) == Unchecked()


def test_a_whole_document_is_placed_while_the_index_holds_it() -> None:
    assert placed(an_annotation(None), chunks_of(BODY, [15])) == Placed(None, None)


def test_a_hint_rewritten_after_each_edit_follows_its_selection() -> None:
    store = AnnotationStore((an_annotation(selecting(BODY, "gains drift slowly")),))
    edited = "Inserted.\n\n" + BODY

    moved = rehinted(store, chunks_of(edited, [26, 74]))

    selector = moved.annotations[0].selector
    assert selector is not None
    assert edited[selector.start : selector.end] == "gains drift slowly"
    assert selector.chunk == 2


def test_a_detached_selection_keeps_its_hint() -> None:
    store = AnnotationStore((an_annotation(selecting(BODY, "gains drift slowly")),))

    assert rehinted(store, chunks_of("Nothing like it.", [])) == store


# ---------------------------------------------------------------------------
# Which chunks carry a tag


def test_a_chunk_carries_its_selections_tags_and_its_document_s() -> None:
    chunks = chunks_of(BODY, [15, 63])
    store = AnnotationStore(
        (
            an_annotation(
                replace(selecting(BODY, "gains drift slowly"), chunk=2), ("b",)
            ),
            an_annotation(None, ("a",), identifier="0000000b"),
        )
    )

    assert tags_on(store, chunks[2]) == [("a", True), ("b", False)]
    assert tags_on(store, chunks[1]) == [("a", True)]


def test_a_chunk_whose_words_differ_from_the_hint_carries_nothing() -> None:
    selector = replace(selecting(BODY, "gains drift slowly"), chunk=2)
    store = AnnotationStore((an_annotation(selector),))
    edited = BODY.replace("drift slowly", "never move")

    assert tags_on(store, chunks_of(edited, [15, 63])[2]) == []


def test_a_tag_on_the_document_and_a_selection_is_said_once() -> None:
    chunks = chunks_of(BODY, [15, 63])
    store = AnnotationStore(
        (
            an_annotation(replace(selecting(BODY, "gains drift slowly"), chunk=2)),
            an_annotation(None, identifier="0000000b"),
        )
    )

    assert tags_on(store, chunks[2]) == [("a", True)]


def test_a_document_tag_admits_every_chunk_of_it_and_no_other() -> None:
    chunks = chunks_of(BODY, [15, 63]) + chunks_of("Other", [], document="other00001")
    admits = admitting(AnnotationStore((an_annotation(None),)), ["a"], chunks)

    assert [admits(chunk) for chunk in chunks] == [True, True, True, False]


def test_a_selection_admits_every_chunk_it_overlaps() -> None:
    """A selection across a chunk boundary is in both chunks; the others
    are not."""
    chunks = chunks_of(BODY, [15, 70, 112])
    start = BODY.index("A second")
    store = AnnotationStore((an_annotation(selector_of(BODY, start, start + 20)),))
    admits = admitting(store, ["a"], chunks)

    assert [admits(chunk) for chunk in chunks] == [False, True, True, False]


def overlapping_windows(text: str, size: int, step: int) -> list[Chunk]:
    """`text` cut as the chunker cuts a long block: windows of `size`,
    each starting `step` after the last, so neighbours overlap."""
    starts = range(0, len(text), step)
    return [
        Chunk(
            id=f"{DOCUMENT}::{number}",
            collection="literature",
            document_id=DOCUMENT,
            chunk_index=number,
            text=text[start : start + size],
            source_path="literature/a.md",
            char_start=start,
            char_end=min(start + size, len(text)),
        )
        for number, start in enumerate(starts)
    ]


WINDOWED = " ".join(f"word{number}" for number in range(120))


def test_a_window_s_own_text_is_up_to_where_the_next_begins() -> None:
    chunks = overlapping_windows(WINDOWED, 200, 150)

    assert own_end(chunks, chunks[1]) == 300
    assert own_end(chunks, chunks[-1]) == len(WINDOWED)
    assert chunk_at(chunks, 160) == 1


def test_a_tag_on_one_window_is_on_no_neighbour() -> None:
    """Windows overlap, so a selection of one window's whole text would
    reach into both neighbours; a tag on a window selects its own text,
    and is on that window alone - for search and for a hit's chips."""
    chunks = overlapping_windows(WINDOWED, 200, 150)
    middle = chunks[1]
    selector = selector_of(
        WINDOWED, middle.char_start, own_end(chunks, middle), middle.chunk_index
    )
    store = AnnotationStore((an_annotation(selector),))
    admits = admitting(store, ["a"], chunks)

    expected = [chunk is middle for chunk in chunks]
    assert len(chunks) > 3, "the fixture no longer has a window on each side"
    assert [admits(chunk) for chunk in chunks] == expected
    assert [bool(tags_on(store, chunk)) for chunk in chunks] == expected


def test_a_detached_selection_admits_nothing() -> None:
    chunks = chunks_of(BODY.replace("drift", "wander"), [15, 63])
    store = AnnotationStore((an_annotation(selecting(BODY, "gains drift slowly")),))
    admits = admitting(store, ["a"], chunks)

    assert not any(admits(chunk) for chunk in chunks)


def test_several_tags_admit_what_all_of_them_name() -> None:
    chunks = chunks_of(BODY, [15, 63])
    store = AnnotationStore(
        (
            an_annotation(selecting(BODY, "gains drift slowly"), ("b",)),
            an_annotation(None, ("a",), identifier="0000000b"),
        )
    )
    admits = admitting(store, ["a", "b"], chunks)

    assert [admits(chunk) for chunk in chunks] == [False, False, True]


def test_a_tag_the_store_does_not_hold_admits_nothing() -> None:
    chunks = chunks_of(BODY, [15])
    admits = admitting(AnnotationStore((an_annotation(None),)), ["z"], chunks)

    assert not any(admits(chunk) for chunk in chunks)
