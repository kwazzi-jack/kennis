"""The narrowest place a chunk can be cited by (Brian, #592, #593).

A figure, table or equation the chunk holds; then (once conversion keeps
them, #568) its page; then the number of its heading or of the nearest
numbered heading above it; then its heading's words; else nothing. The
fixtures are shaped as MinerU and arXiv's HTML write a paper.
"""

from __future__ import annotations

import pytest

from kennis.engine.citing.locators import Locator, locator_of

PAPER = """\
# A paper about gains

## Abstract

We solve for gains.

## 1 Introduction

Gains drift. As Figure 2 shows, they drift slowly.

## 2 Method

## 2.1 Data reduction

The data were flagged.

Figure 3. The flagged fraction per antenna.

More words about flagging.

$$
g = \\frac{V}{M} \\tag{4}
$$

## Implementation details

Written in Python.

```text
## 9 Not a heading
```

After the code.

## 3.1.2 Deeper

Text in a sub-subsection.

**Table 2:** Antenna positions.

## A.1 An appendix

Appendix text.
"""


def span_of(text: str, body: str = PAPER) -> tuple[int, int]:
    start = body.index(text)
    return start, start + len(text)


def located(text: str, body: str = PAPER) -> Locator | None:
    start, end = span_of(text, body)
    return locator_of(body, start, end)


def test_a_caption_in_the_chunk_is_its_locator():
    assert located("Figure 3. The flagged fraction per antenna.") == Locator(
        "figure", "3"
    )


def test_an_equation_s_tag_in_the_chunk_is_its_locator():
    assert located("g = \\frac{V}{M} \\tag{4}") == Locator("equation", "4")


def test_the_first_of_several_in_the_chunk_is_named():
    both = (
        "Figure 3. The flagged fraction per antenna.\n\n"
        "More words about flagging.\n\n$$\ng = \\frac{V}{M} \\tag{4}"
    )
    assert located(both) == Locator("figure", "3")
    later = "More words about flagging.\n\n$$\ng = \\frac{V}{M} \\tag{4}"
    assert located(later) == Locator("equation", "4")


def test_a_table_caption_in_bold_is_a_table():
    assert located("**Table 2:** Antenna positions.") == Locator("table", "2")


def test_a_mention_in_running_text_is_not_a_caption():
    """ "As Figure 2 shows" points elsewhere; the chunk is cited by its
    section instead."""
    assert located("Gains drift. As Figure 2 shows, they drift slowly.") == Locator(
        "section", "1"
    )


def test_a_numbered_heading_is_cited_by_its_number():
    assert located("The data were flagged.") == Locator("section", "2.1")
    assert located("Text in a sub-subsection.") == Locator("section", "3.1.2")


def test_an_appendix_numbering_is_a_section_number():
    assert located("Appendix text.") == Locator("section", "A.1")


def test_an_unnumbered_heading_is_cited_by_its_words():
    """At the same markdown level as the numbered heading before it, so not
    beneath it: its own words tell two passages apart (#593)."""
    assert located("Written in Python.") == Locator("section", "Implementation details")
    assert located("We solve for gains.") == Locator("section", "Abstract")


def test_a_chunk_that_begins_with_its_heading_is_under_that_heading():
    assert located("## 2.1 Data reduction\n\nThe data were flagged.") == Locator(
        "section", "2.1"
    )


def test_a_heading_inside_a_fenced_block_is_not_one():
    """The passage after the block is still under the heading before it."""
    assert located("After the code.") == Locator("section", "Implementation details")


def test_text_before_any_heading_has_no_locator():
    body = "Some words before any heading.\n\n# Title\n\nMore.\n"
    assert located("Some words before any heading.", body) is None


def test_the_title_alone_above_a_chunk_is_not_a_section():
    """The document's own title is the one top-level heading, and naming it
    adds nothing to a citation that already names the paper."""
    body = "# A paper about gains\n\nOpening words.\n"
    assert located("Opening words.", body) is None


def test_a_numbered_parent_names_an_unnumbered_child():
    """Where the markdown levels say one heading is beneath another, the
    nearest numbered one above names the chunk."""
    body = "# Title\n\n## 3 Results\n\n### Details\n\nThe result.\n"
    assert located("The result.", body) == Locator("section", "3")


@pytest.mark.parametrize(
    ("heading", "number"),
    [
        ("## 2 OBSERVATIONS", "2"),
        ("## 4.1.10 FRB 20231020B", "4.1.10"),
        ("## 3. Results", "3"),
        ("## IV. DISCUSSION", "IV"),
        ("## Appendix B The noise model", "B"),
        ("## **2.1 Data reduction**", "2.1"),
    ],
)
def test_the_number_is_read_as_papers_write_it(heading: str, number: str):
    body = f"# Title\n\n{heading}\n\nThe text.\n"
    assert located("The text.", body) == Locator("section", number)


@pytest.mark.parametrize(
    "heading",
    ["## 2011 observations", "## A Method", "## Results"],
)
def test_a_heading_that_only_looks_numbered_is_cited_by_its_words(heading: str):
    body = f"# Title\n\n{heading}\n\nThe text.\n"
    words = heading.removeprefix("## ")
    assert located("The text.", body) == Locator("section", words)


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Figure 1: Comparison of architectures.", Locator("figure", "1")),
        ("Fig. 3: A plot.", Locator("figure", "3")),
        ("FIG. 12. The spectrum.", Locator("figure", "12")),
        ("**Figure 4.** A bold caption.", Locator("figure", "4")),
        ("Figure A1. An appendix figure.", Locator("figure", "A1")),
        ("Table 1. FRB localization general properties.", Locator("table", "1")),
        ("TABLE 3 | Sources.", Locator("table", "3")),
    ],
)
def test_captions_are_read_as_papers_write_them(caption: str, expected: Locator):
    body = f"# Title\n\n## 1 Intro\n\n{caption}\n"
    assert located(caption, body) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Figure 3 shows the flagged fraction.",
        "Table 2 lists the antennas.",
        "Figures 3 and 4 compare them.",
    ],
)
def test_a_sentence_beginning_with_a_figure_is_not_a_caption(line: str):
    body = f"# Title\n\n## 1 Intro\n\n{line}\n"
    assert located(line, body) == Locator("section", "1")


@pytest.mark.parametrize(
    ("heading", "words"),
    [
        ("## a b s t r a c t", "abstract"),
        ("## A B S T R A C T", "ABSTRACT"),
        # Words of their own are kept as written.
        ("## A New Method", "A New Method"),
        ("## X and Y", "X and Y"),
    ],
)
def test_a_letter_spaced_heading_is_read_as_its_word(heading: str, words: str):
    """A PDF that sets a heading in spaced capitals reaches the markdown one
    letter at a time, and `sec. a b s t r a c t` reads as noise (#597)."""
    body = f"# Title\n\n{heading}\n\nThe text.\n"
    assert located("The text.", body) == Locator("section", words)
