"""Rendering one ranked search hit.

The relevance band is the part worth testing hard. It is a claim about how
well a passage matched, and the two obvious ways to compute it - from the
fused score, and from the hit's position in its own candidate pool - both
say nothing or say something false. Concerns #186 and #198.
"""

from __future__ import annotations

import pytest

from kennis.engine.rag.models import Chunk, SearchResult
from kennis.render.hits import (
    CALIBRATED_MODELS,
    Hit,
    basis_phrase,
    hit_detail,
    hit_detail_parts,
    hit_handle,
    hit_headline,
    raw_scores,
    relevance_phrase,
    relevances,
    score_style_for,
)

_CALIBRATED = "BAAI/bge-small-en-v1.5"


def a_hit(
    *,
    document_id: str = "zrf1299xo1",
    chunk_index: int = 0,
    title: str = "Rivers",
    section: str | None = "Deposition",
    score: float = 0.031,
    bm25_score: float | None = None,
    dense_score: float | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            id=f"{document_id}::{chunk_index}",
            collection="notes",
            document_id=document_id,
            chunk_index=chunk_index,
            text="Rivers carry sediment.",
            source_path="notes/Rivers.md",
            char_start=0,
            char_end=22,
            section=section,
            metadata={"title": title},
        ),
        score=score,
        bm25_score=bm25_score,
        dense_score=dense_score,
    )


def _band(
    result: SearchResult,
    leg: str,
    *,
    model: str | None = _CALIBRATED,
    best: float = 1.0,
) -> str | None:
    """One leg's band, or None when that leg did not score.

    `relevances` returns every leg at once, which is the point of it;
    these tests are about one scale's cuts at a time, so they ask for
    one.
    """
    return dict(relevances(result, model=model, best=best)).get(leg)


def _banded_hit(
    *, bm25_score: float | None = None, dense_score: float | None = None
) -> Hit:
    return Hit(
        collection="notes",
        result=a_hit(bm25_score=bm25_score, dense_score=dense_score),
        model=_CALIBRATED,
    )


# ---------------------------------------------------------------------------
# The headline
# ---------------------------------------------------------------------------


def test_a_headline_carries_the_rank_title_and_section():
    headline = hit_headline(3, a_hit())

    assert headline.startswith("[3] ")
    assert "Rivers" in headline
    assert "Deposition" in headline


def test_a_headline_does_not_name_the_collection():
    """The group heading above it does. Repeating it on every hit is noise
    that was only needed while the list was three lists interleaved.
    Concern #231."""
    headline = hit_headline(1, a_hit())

    assert "[literature]" not in headline
    assert "[notes]" not in headline


def test_a_headline_does_not_repeat_the_title_as_its_section():
    """A short document's only heading is its title."""
    assert hit_headline(1, a_hit(section="Rivers")).count("Rivers") == 1


def test_a_headline_does_not_repeat_a_title_that_differs_only_by_case():
    """`calibration - Calibration` was the real output: a title taken
    from a filename beside an H1 written in prose case, which is the
    ordinary relationship between the two rather than an odd one.

    A heading that differs from the title only in case carries nothing
    the title does not, so there is nothing to lose by suppressing it.
    Concern #296.
    """
    headline = hit_headline(1, a_hit(title="calibration", section="Calibration"))

    assert headline == "[1] calibration"


def test_a_headline_keeps_a_section_that_differs_by_more_than_case():
    """The other side of the comparison, so the test above cannot pass
    by suppressing every section."""
    headline = hit_headline(1, a_hit(title="calibration", section="Calibration notes"))

    assert "Calibration notes" in headline


def test_a_handle_carries_what_read_takes():
    """`kennis read <id> --chunk <n>`, so both have to be on the line."""
    handle = hit_handle(a_hit(document_id="abc1234567", chunk_index=4))

    assert "id=abc1234567" in handle
    assert "chunk=4" in handle


# ---------------------------------------------------------------------------
# Each leg says its own score
# ---------------------------------------------------------------------------


def test_an_exact_lexical_match_is_not_reported_as_low():
    """The defect this unit exists for.

    Under hybrid search `basis_for` returned `"cosine"` and
    `relevance` banded the dense leg alone, so BM25 never spoke. A
    one-word query embeds to a modest cosine against a full chunk,
    and a search for `selfcal` that highlighted the literal word in
    the passage reported `relevance: low`.

    Both legs now answer for themselves."""
    found = relevances(
        a_hit(bm25_score=9.0, dense_score=0.58), model=_CALIBRATED, best=9.0
    )

    assert dict(found)["lexical"] == "very high"
    assert dict(found)["meaning"] == "low"


def test_a_leg_that_did_not_score_says_nothing():
    """Which is what removed `basis_for`: there is no choice to make
    any more, only two questions each answered or not."""
    lexical_only = relevances(a_hit(bm25_score=4.0), model=_CALIBRATED, best=4.0)
    dense_only = relevances(a_hit(dense_score=0.81), model=_CALIBRATED, best=0.0)

    assert [leg for leg, _ in lexical_only] == ["lexical"]
    assert [leg for leg, _ in dense_only] == ["meaning"]


def test_an_uncalibrated_model_has_no_meaning_band():
    """A band is a claim on a scale, and kennis has not measured this
    one. Concern #198: the cuts belong to the model, not to kennis.
    The lexical band is unaffected - it is relative to this query's
    own best and needs no calibration."""
    found = relevances(
        a_hit(bm25_score=4.0, dense_score=0.9),
        model="text-embedding-3-small",
        best=4.0,
    )

    assert [leg for leg, _ in found] == ["lexical"]

    unknown = relevances(a_hit(dense_score=0.9), model=None, best=0.0)
    assert unknown == ()


def test_the_legs_are_reported_in_a_fixed_order():
    """Lexical first, because it is the one a reader can check by
    eye against the passage."""
    both = relevances(
        a_hit(bm25_score=4.0, dense_score=0.81), model=_CALIBRATED, best=4.0
    )

    assert [leg for leg, _ in both] == ["lexical", "meaning"]


def test_the_calibrated_model_is_the_default_one():
    """If the default embedding model changes, this fails rather than
    silently banding on cuts measured for a different model."""
    from kennis.engine.settings import Settings

    assert Settings().embedding.model in CALIBRATED_MODELS


def test_the_phrase_describes_every_leg_the_group_has():
    """**Relevance is never shown without its scale**, and there are
    now two scales that mean genuinely different things: a position
    relative to this query's own best lexical hit, and an absolute
    cosine against measured cuts.

    The old phrase refused when a group mixed them - "one sentence
    cannot describe both" - which was a consequence of there being
    one band. With two labels the sentence describes both, and
    mixing is the ordinary case."""
    both = [_banded_hit(bm25_score=4.0, dense_score=0.81)]
    lexical = [_banded_hit(bm25_score=4.0)]

    phrase = basis_phrase(both, "human")
    assert "lexical" in phrase and "meaning" in phrase
    assert "cosine" in phrase

    only = basis_phrase(lexical, "human")
    assert "lexical" in only
    assert "cosine" not in only


def test_a_detail_line_labels_every_band_it_shows():
    """A level with no leg on it is the defect this unit fixes wearing
    a different hat: `relevance: low` gave the reader no way to know
    which of two incomparable scales it was on.

    The handle stays last, because it is what `kennis read` takes and
    a reader copying it should not have to find it among the bands."""
    line = hit_detail(
        _banded_hit(bm25_score=9.0, dense_score=0.58), style="human", best=9.0
    )

    assert line.index("lexical: very high") < line.index("meaning: low")
    assert line.index("meaning: low") < line.index("id=")
    assert "chunk=0" in line


def test_the_line_is_exactly_the_parts_joined():
    """Two representations of one thing, and nothing keeps them in step
    but this. The window lays the fields out itself because a
    twenty-character gutter cannot be trusted to wrap between them;
    the command line prints the line. If they drift, the byte-identical
    property design section 20 asks for is quietly gone. Concern #380.

    Every style, because `none` and `raw` compose different fields."""
    hit = _banded_hit(bm25_score=9.0, dense_score=0.58)

    for style in ("human", "raw", "none"):
        parts = hit_detail_parts(hit, style=style, best=9.0)
        assert "  ".join(parts) == hit_detail(hit, style=style, best=9.0)
        assert all(part == part.strip() for part in parts), parts


def test_a_field_never_contains_the_separator():
    """Which is what makes the two representations interchangeable: a
    field holding two spaces would join into a line that no longer
    splits back into the fields it came from."""
    for hit in (
        _banded_hit(bm25_score=9.0, dense_score=0.58),
        _banded_hit(bm25_score=9.0),
        _banded_hit(dense_score=0.58),
    ):
        for style in ("human", "raw", "none"):
            parts = hit_detail_parts(hit, style=style, best=9.0)
            assert not any("  " in part for part in parts), parts


def test_a_detail_line_omits_a_leg_that_did_not_score():
    """Not "meaning: very low" - that is a measurement, and no
    measurement was taken."""
    line = hit_detail(_banded_hit(bm25_score=9.0), style="human", best=9.0)

    assert "lexical: " in line
    assert "meaning" not in line


def test_raw_numbers_appear_only_when_no_leg_can_be_banded():
    """`score_style_for` used to ask whether a single chosen scale
    existed, so a hybrid search on a model kennis has not measured
    fell back to raw numbers although its lexical band was perfectly
    good. It now degrades only when nothing at all can be banded.
    Concern #379."""
    uncalibrated = Hit(
        collection="notes",
        result=a_hit(bm25_score=4.0, dense_score=0.9),
        model="text-embedding-3-small",
    )
    unbandable = Hit(collection="notes", result=a_hit(dense_score=0.9), model=None)

    assert score_style_for([uncalibrated], "human") == ("human", False)
    assert score_style_for([unbandable], "human") == ("raw", True)


def test_a_style_the_reader_asked_for_is_never_overridden():
    """The degradation exists because "human" cannot be honoured, not
    because kennis prefers numbers."""
    unbandable = [Hit(collection="notes", result=a_hit(dense_score=0.9), model=None)]

    assert score_style_for(unbandable, "raw") == ("raw", False)
    assert score_style_for(unbandable, "none") == ("none", False)


def test_the_phrase_puts_its_clauses_in_the_fixed_order():
    """Given the legs the other way round, and given them as a set with
    no order of its own. The order belongs to `relevance_phrase`, which
    is why its caller no longer sorts: the same rule in two places is
    one whose removal from either cannot be observed. Concern #379."""
    reversed_order = relevance_phrase(["meaning", "lexical"])
    unordered = relevance_phrase({"meaning", "lexical"})

    assert reversed_order.index("lexical") < reversed_order.index("meaning")
    assert unordered == reversed_order


def test_no_phrase_is_offered_when_no_level_is_printed():
    """A report of raw scores must not carry a heading explaining a
    column it does not have."""
    hits = [_banded_hit(bm25_score=4.0, dense_score=0.81)]

    assert basis_phrase(hits, "raw") == ""
    assert basis_phrase(hits, "none") == ""


# ---------------------------------------------------------------------------
# The cosine band, at the cuts that were measured
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cosine", "expected"),
    [
        (0.816, "very high"),
        (0.801, "very high"),
        (0.800, "very high"),
        (0.793, "high"),
        (0.765, "high"),
        (0.700, "medium"),
        (0.607, "low"),
        (0.567, "low"),
        (0.544, "very low"),
        (0.377, "very low"),
    ],
)
def test_the_cosine_band_matches_what_was_measured(cosine: float, expected: str):
    """Every value here is one the calibration run produced against Brian's
    corpus: the real queries' best hits, the nonsense queries' best hits, and
    the floor. Concern #198."""
    hit = a_hit(dense_score=cosine)

    assert _band(hit, "meaning", best=0.816) == expected


def test_a_real_query_and_a_nonsense_query_land_in_different_bands():
    """The property the cuts exist for. Measured: real top hits 0.765-0.816,
    nonsense top hits 0.567-0.607, with nothing between them."""
    real = [0.765, 0.765, 0.793, 0.801, 0.816]
    nonsense = [0.567, 0.574, 0.600, 0.607]

    banded_real = {
        _band(a_hit(dense_score=value), "meaning", best=1.0) for value in real
    }
    banded_nonsense = {
        _band(a_hit(dense_score=value), "meaning", best=1.0) for value in nonsense
    }

    assert banded_real <= {"high", "very high"}
    assert banded_nonsense <= {"low", "very low"}


def test_the_cosine_band_does_not_depend_on_the_other_hits():
    """An absolute scale is the whole point: the same passage scores the
    same whatever it is shown beside."""
    hit = a_hit(dense_score=0.70)

    alone = _band(hit, "meaning", best=0.70)
    beside = _band(hit, "meaning", best=0.99)

    assert alone == beside == "medium"


# ---------------------------------------------------------------------------
# The lexical band, which is relative and says so
# ---------------------------------------------------------------------------


def test_the_lexical_band_is_a_fraction_of_the_best_hit():
    """BM25 is unbounded and corpus-relative, so the only honest reading is
    against the other hits of the same query."""
    best = a_hit(bm25_score=20.0)
    middling = a_hit(bm25_score=10.0)
    poor = a_hit(bm25_score=1.0)

    assert _band(best, "lexical", model=None, best=20.0) == "very high"
    assert _band(middling, "lexical", model=None, best=20.0) == "medium"
    assert _band(poor, "lexical", model=None, best=20.0) == "very low"


def test_the_best_lexical_hit_is_always_the_top_band():
    """By construction, which is exactly why `relevance_phrase` has to say
    the band is relative."""
    for best in (0.1, 5.0, 900.0):
        hit = a_hit(bm25_score=best)
        assert _band(hit, "lexical", model=None, best=best) == "very high"


def test_a_band_needs_a_score_on_the_leg_it_bands():
    """A hybrid hit found only by the lexical leg has no cosine. Saying
    nothing is correct; inventing one is not."""
    assert _band(a_hit(), "meaning", best=0.8) is None
    assert _band(a_hit(), "lexical", model=None, best=1.0) is None


def test_a_zero_best_score_does_not_divide_by_zero():
    hit = a_hit(bm25_score=0.0)

    assert _band(hit, "lexical", model=None, best=0.0) is not None


# ---------------------------------------------------------------------------
# Raw scores
# ---------------------------------------------------------------------------


def test_raw_scores_name_every_leg_that_ran():
    shown = raw_scores(a_hit(score=0.0312, bm25_score=12.31, dense_score=0.8742))

    assert "rrf=0.0312" in shown
    assert "bm25=12.31" in shown
    assert "cos=0.874" in shown


def test_raw_scores_omit_a_leg_that_did_not_run():
    """None is "this leg did not run", and printing it as 0 would read as
    "this leg ran and found nothing"."""
    shown = raw_scores(a_hit(score=0.0164, bm25_score=12.31))

    assert "cos=" not in shown
    assert "bm25=12.31" in shown
