"""A selection made in the window, found in the document's markdown, and
an annotation made, changed and removed by its id (#50, unit 2; sketch
2026-11-16-annotate-selection)."""

from __future__ import annotations

from html.parser import HTMLParser
from itertools import pairwise

import pytest

from annotating import whole_document
from kennis.engine.annotations import (
    AnnotationStore,
    Span,
    annotated,
    removed,
    revised,
    selection_in,
    selector_of,
    visible_words,
)
from kennis.engine.errors import KennisError
from kennis.render.html import _line_offsets, drawn_text, to_html


def blocks_of(body: str) -> list[Span]:
    """Each paragraph of `body` as the page's `data-source` gives it: from
    its first line's offset to the offset after its last line."""
    offsets = _line_offsets(body)
    spans: list[Span] = []
    start: int | None = None
    for line, (begin, end) in enumerate(pairwise(offsets)):
        blank = not body[begin:end].strip()
        if not blank and start is None:
            start = begin
        if start is not None and (blank or line == len(offsets) - 2):
            spans.append(Span(start, begin if blank else end))
            start = None
    return spans


BODY = (
    "# Calibration\n"
    "\n"
    "The *gains* drift slowly, see [the paper](https://example.org/p) for\n"
    "details. The gains drift slowly in time.\n"
    "\n"
    "1. first we solve\n"
    "2. then we apply the solutions\n"
    "\n"
    "The phase $\\phi_{pq}$ is wrapped, and the gains drift slowly.\n"
)


def found(
    text: str, before: str = "", *, first: int = 1, last: int | None = None
) -> str | None:
    blocks = blocks_of(BODY)
    span = selection_in(
        BODY, blocks[first], blocks[first if last is None else last], text, before
    )
    return None if span is None else BODY[span.start : span.end]


def test_the_fixture_has_the_blocks_the_tests_name() -> None:
    blocks = [BODY[span.start : span.end] for span in blocks_of(BODY)]
    assert blocks[0].startswith("# Calibration")
    assert blocks[1].startswith("The *gains*")
    assert blocks[2].startswith("1. first")
    assert blocks[3].startswith("The phase")


# Written by hand (#373): what is selected on the page, and the markdown
# the selection must come back as.
FOUND_CASES = [
    ("across an emphasis", "The gains drift", "The *gains* drift"),
    (
        "across a link",
        "see the paper for",
        "see [the paper](https://example.org/p) for",
    ),
    ("from inside a word", "ains drift", "ains* drift"),
    ("across a line break", "for details", "for\ndetails"),
]


@pytest.mark.parametrize(
    ("selected", "expected"),
    [(selected, expected) for _, selected, expected in FOUND_CASES],
    ids=[case for case, _, _ in FOUND_CASES],
)
def test_a_selection_is_found_as_the_markdown_it_was_drawn_from(
    selected: str, expected: str
) -> None:
    assert found(selected) == expected


def test_an_ordered_list_s_numbers_stand_between_its_items() -> None:
    assert found("first we solve then we", first=2) == "first we solve\n2. then we"


def test_maths_is_found_by_its_tex() -> None:
    assert found("phase \\phi_{pq} is", first=3) == "phase $\\phi_{pq}$ is"


def test_repeated_words_are_told_apart_by_what_comes_before() -> None:
    blocks = blocks_of(BODY)
    span = selection_in(
        BODY, blocks[1], blocks[1], "gains drift slowly", "for details. The "
    )

    assert span is not None
    assert BODY[span.start - 4 : span.end] == "The gains drift slowly"
    assert BODY[span.end : span.end + 3] == " in"


def test_with_nothing_before_the_first_occurrence_is_taken() -> None:
    blocks = blocks_of(BODY)
    span = selection_in(BODY, blocks[1], blocks[1], "gains drift slowly", "")

    assert span is not None
    assert BODY[span.start - 1 : span.end] == "*gains* drift slowly"


def test_a_selection_must_begin_in_its_first_block() -> None:
    """The same words in a later block are not this selection."""
    assert found("is wrapped", first=1, last=3) is None


def test_a_selection_across_blocks_is_found() -> None:
    selected = "in time. first we solve"

    assert found(selected, first=1, last=2) == "in time.\n\n1. first we solve"


def test_words_that_are_not_there_are_not_found() -> None:
    assert found("the gains wander") is None


def test_a_selection_of_no_words_is_not_found() -> None:
    assert found(" , . ") is None


def test_the_words_drawn_drop_a_link_s_address_and_maths_delimiters() -> None:
    assert visible_words("see [the paper](https://example.org/p) for") == (
        "see",
        "the",
        "paper",
        "for",
    )
    assert visible_words("phase $\\phi_{pq}$ is") == ("phase", "phi_", "pq", "is")


# ---------------------------------------------------------------------------
# Making, changing and removing


SELECTOR = selector_of(BODY, 18, 36)


def test_annotating_makes_one_annotation_with_tags_and_a_comment() -> None:
    store, annotation = annotated(
        AnnotationStore(), "paper00001", SELECTOR, ("calibration",), "check this"
    )

    assert store.annotations == (annotation,)
    assert annotation.tags == ("calibration",)
    assert annotation.comment == "check this"
    assert annotation.selector == SELECTOR


def test_a_comment_alone_is_an_annotation() -> None:
    store, annotation = annotated(AnnotationStore(), "paper00001", SELECTOR, (), "why?")

    assert annotation.tags == ()
    assert store.annotations == (annotation,)


def test_neither_tags_nor_comment_is_refused() -> None:
    with pytest.raises(KennisError):
        annotated(AnnotationStore(), "paper00001", SELECTOR, (), "  ")


def test_the_same_selection_again_gains_the_tags_and_the_comment() -> None:
    store, first = annotated(AnnotationStore(), "paper00001", SELECTOR, ("a",), None)

    store, again = annotated(store, "paper00001", SELECTOR, ("b",), "now a comment")

    assert again.id == first.id
    assert store.annotations == (again,)
    assert again.tags == ("a", "b")
    assert again.comment == "now a comment"


def test_revising_replaces_tags_and_comment() -> None:
    store, annotation = annotated(
        AnnotationStore(), "paper00001", SELECTOR, ("a",), "x"
    )

    store = revised(store, annotation.id, ("b", "c"), "y")

    (changed,) = store.annotations
    assert (changed.id, changed.tags, changed.comment) == (
        annotation.id,
        ("b", "c"),
        "y",
    )


def test_revising_away_tags_and_comment_drops_the_annotation() -> None:
    store, annotation = annotated(
        AnnotationStore(), "paper00001", SELECTOR, ("a",), "x"
    )

    assert revised(store, annotation.id, (), "").annotations == ()


def test_removing_takes_that_annotation_alone() -> None:
    store = AnnotationStore((whole_document("paper00001", ("keep",), "0000000b"),))
    store, annotation = annotated(store, "paper00001", SELECTOR, ("a",), None)

    store = removed(store, annotation.id)

    assert [each.id for each in store.annotations] == ["0000000b"]


@pytest.mark.parametrize("change", ["revise", "remove"])
def test_an_unknown_id_is_refused(change: str) -> None:
    store = AnnotationStore((whole_document("paper00001", ("keep",)),))

    with pytest.raises(KennisError, match="ffffffff"):
        if change == "revise":
            revised(store, "ffffffff", ("a",), None)
        else:
            removed(store, "ffffffff")


# ---------------------------------------------------------------------------
# Where each block is, for the page's script


EVERY_BLOCK = (
    "# Head\n"
    "\n"
    "Para *x* $y$.\n"
    "\n"
    "- a\n"
    "- b\n"
    "\n"
    "> quote\n"
    "\n"
    "```python\n"
    "x = 1\n"
    "```\n"
    "\n"
    "```\n"
    "plain\n"
    "```\n"
    "\n"
    "$$\n"
    "a = b\n"
    "$$\n"
    "\n"
    "| a | b |\n"
    "|---|---|\n"
    "| 1 | 2 |\n"
    "\n"
    "---\n"
)

# Written by hand (#373): each top-level block's markdown, in order.
EXPECTED_BLOCKS = [
    "# Head\n",
    "Para *x* $y$.\n",
    "- a\n- b\n",
    "> quote\n",
    "```python\nx = 1\n```\n",
    "```\nplain\n```\n",
    "$$\na = b\n$$\n",
    "| a | b |\n|---|---|\n| 1 | 2 |\n",
    "---\n",
]


class TopLevel(HTMLParser):
    """The `data-source` of each element at the top of the output, or
    None for one without it."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.sources: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth == 0:
            self.sources.append(dict(attrs).get("data-source"))
        if tag not in ("hr", "br", "img"):
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        self.depth -= 1


def test_every_top_level_block_says_where_its_markdown_is() -> None:
    reader = TopLevel()
    reader.feed(to_html(EVERY_BLOCK, source_offsets=True))

    assert None not in reader.sources
    blocks = []
    for source in reader.sources:
        assert source is not None
        start, end = (int(part) for part in source.split())
        blocks.append(EVERY_BLOCK[start:end].strip("\n") + "\n")
    assert blocks == EXPECTED_BLOCKS


def test_without_asking_no_block_says_where_it_is() -> None:
    assert "data-source" not in to_html(EVERY_BLOCK)


# Written by hand (#373): a selection's markdown, and the words a listing of
# it quotes - as the page draws them.
DRAWN_CASES = [
    (
        "a link's address",
        "see [the paper](https://example.org/p) for",
        "see the paper for",
    ),
    ("an emphasis begun before the selection", "gains* drift", "gains drift"),
    ("an emphasis ended after it", "drift *slowly", "drift slowly"),
    ("a word's own underscore", "the snake_case name", "the snake_case name"),
    ("maths, as its TeX", "phase $\\phi_{pq}$ is", "phase $\\phi_{pq}$ is"),
    ("code, as it stands", "call `a_b*` here", "call a_b* here"),
    ("a line break", "for\ndetails", "for details"),
]


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [(markdown, expected) for _, markdown, expected in DRAWN_CASES],
    ids=[case for case, _, _ in DRAWN_CASES],
)
def test_a_selection_is_quoted_as_the_page_draws_it(
    markdown: str, expected: str
) -> None:
    assert drawn_text(markdown) == expected
