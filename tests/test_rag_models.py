"""The search-facing data models, and filtering over chunk metadata.

These are deliberately source-agnostic: a chunk carries a small set of typed
provenance fields plus whatever the loader attached. Filters therefore work
over a dotted path, because kennis frontmatter namespaces its per-collection
fields into a block - `bib.year`, `docs.project` - and a filter naming a
plain key could not reach them.
"""

from __future__ import annotations

from typing import Any

import pytest

from kennis.engine.rag.models import Chunk, Filter, combine_filters


def a_chunk(**metadata: Any) -> Chunk:
    return Chunk(
        id="doc1::0",
        collection="literature",
        document_id="doc1",
        chunk_index=0,
        text="Body.",
        source_path="/corpus/literature/Paper.md",
        char_start=0,
        char_end=5,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Reaching a field
# ---------------------------------------------------------------------------


def test_a_plain_field_is_a_top_level_key():
    chunk = a_chunk(title="A Paper")
    assert Filter(field="title", op="eq", value="A Paper").predicate()(chunk)


def test_a_dotted_field_follows_the_frontmatter_block():
    """The reason dotted paths exist: every collection-specific field kennis
    writes lives inside a namespaced block."""
    chunk = a_chunk(bib={"year": "2011", "citekey": "smirnov2011"})
    assert Filter(field="bib.year", op="eq", value="2011").predicate()(chunk)


def test_a_field_that_is_not_there_does_not_match():
    """A missing field is false rather than an error: a filter runs over a
    mixed collection where not every chunk has every field."""
    assert not Filter(field="bib.year", op="eq", value="2011").predicate()(a_chunk())


def test_a_dotted_path_through_a_non_mapping_does_not_match():
    assert not Filter(field="bib.year", op="eq", value="2011").predicate()(
        a_chunk(bib="not a block")
    )


# ---------------------------------------------------------------------------
# The operators
# ---------------------------------------------------------------------------


def test_in_matches_membership():
    chunk = a_chunk(bib={"year": "2011"})
    assert Filter(field="bib.year", op="in", value=["2010", "2011"]).predicate()(chunk)


def test_contains_ignores_case():
    chunk = a_chunk(title="Revisiting the Measurement Equation")
    assert Filter(field="title", op="contains", value="MEASUREMENT").predicate()(chunk)


def test_gte_and_lte_compare_numerically_when_both_sides_are_numbers():
    """A year is a string in frontmatter, so a lexical comparison would make
    '999' greater than '2011'."""
    chunk = a_chunk(bib={"year": "2011"})

    assert Filter(field="bib.year", op="gte", value=999).predicate()(chunk)
    assert Filter(field="bib.year", op="lte", value="2020").predicate()(chunk)


def test_gte_falls_back_to_comparing_as_text():
    chunk = a_chunk(title="beta")
    assert Filter(field="title", op="gte", value="alpha").predicate()(chunk)


# ---------------------------------------------------------------------------
# Group globs
# ---------------------------------------------------------------------------


def test_a_star_stops_at_a_separator_and_a_double_star_spans_them():
    one_deep = a_chunk(group="quartical/gains")
    two_deep = a_chunk(group="quartical/gains/solver")

    assert Filter(field="group", op="glob", value="quartical/*").predicate()(one_deep)
    assert Filter(field="group", op="glob", value="**/solver").predicate()(two_deep)


def test_selecting_a_group_selects_what_is_filed_under_it():
    """Selecting a group and not its contents would be useless for filtering,
    so a pattern matching a group reaches its descendants too."""
    nested = a_chunk(group="calibration/gains/delay")
    assert Filter(field="group", op="glob", value="calibration").predicate()(nested)


def test_a_group_glob_does_not_match_an_unrelated_group():
    assert not Filter(field="group", op="glob", value="calibration").predicate()(
        a_chunk(group="imaging/deconvolution")
    )


# ---------------------------------------------------------------------------
# Combining
# ---------------------------------------------------------------------------


def test_filters_are_combined_with_and():
    chunk = a_chunk(bib={"year": "2011"}, title="A Paper")
    both = combine_filters(
        [
            Filter(field="bib.year", op="eq", value="2011"),
            Filter(field="title", op="contains", value="paper"),
        ]
    )
    neither = combine_filters(
        [
            Filter(field="bib.year", op="eq", value="2011"),
            Filter(field="title", op="contains", value="thesis"),
        ]
    )

    assert both is not None and both(chunk)
    assert neither is not None and not neither(chunk)


@pytest.mark.parametrize("filters", [None, []])
def test_no_filters_is_no_predicate_rather_than_one_that_always_passes(
    filters: list[Filter] | None,
):
    """The caller skips filtering entirely rather than running a predicate
    over every chunk to learn that it passes."""
    assert combine_filters(filters) is None
