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
    basis_for,
    hit_handle,
    hit_headline,
    raw_scores,
    relevance,
    relevance_phrase,
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


# ---------------------------------------------------------------------------
# The headline
# ---------------------------------------------------------------------------


def test_a_headline_carries_the_rank_collection_title_and_section():
    headline = hit_headline(3, "literature", a_hit())

    assert headline.startswith("[3] ")
    assert "[literature]" in headline
    assert "Rivers" in headline
    assert "Deposition" in headline


def test_a_headline_does_not_repeat_the_title_as_its_section():
    """A short document's only heading is its title."""
    assert hit_headline(1, "notes", a_hit(section="Rivers")).count("Rivers") == 1


def test_a_handle_carries_what_read_takes():
    """`kennis read <id> --chunk <n>`, so both have to be on the line."""
    handle = hit_handle(a_hit(document_id="abc1234567", chunk_index=4))

    assert "id=abc1234567" in handle
    assert "chunk=4" in handle


# ---------------------------------------------------------------------------
# Which basis is in force
# ---------------------------------------------------------------------------


def test_a_calibrated_model_with_a_dense_leg_bands_on_cosine():
    assert basis_for(_CALIBRATED, dense_ran=True) == "cosine"


def test_a_lexical_only_search_bands_relative_to_the_best_hit():
    assert basis_for(_CALIBRATED, dense_ran=False) == "lexical"


def test_an_uncalibrated_model_has_no_band_at_all():
    """A band is a claim on a scale, and kennis has not measured this one.
    Concern #198: the cuts belong to the model, not to kennis."""
    assert basis_for("text-embedding-3-small", dense_ran=True) is None
    assert basis_for(None, dense_ran=True) is None


def test_the_calibrated_model_is_the_default_one():
    """If the default embedding model changes, this fails rather than
    silently banding on cuts measured for a different model."""
    from kennis.engine.settings import Settings

    assert Settings().embedding.model in CALIBRATED_MODELS


def test_each_basis_is_phrased_differently():
    """The two make different claims and a reader has to be told which."""
    assert relevance_phrase("cosine") != relevance_phrase("lexical")
    assert "cosine" in relevance_phrase("cosine")


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

    assert relevance(hit, basis="cosine", model=_CALIBRATED, best=0.816) == expected


def test_a_real_query_and_a_nonsense_query_land_in_different_bands():
    """The property the cuts exist for. Measured: real top hits 0.765-0.816,
    nonsense top hits 0.567-0.607, with nothing between them."""
    real = [0.765, 0.765, 0.793, 0.801, 0.816]
    nonsense = [0.567, 0.574, 0.600, 0.607]

    banded_real = {
        relevance(a_hit(dense_score=value), basis="cosine", model=_CALIBRATED, best=1.0)
        for value in real
    }
    banded_nonsense = {
        relevance(a_hit(dense_score=value), basis="cosine", model=_CALIBRATED, best=1.0)
        for value in nonsense
    }

    assert banded_real <= {"high", "very high"}
    assert banded_nonsense <= {"low", "very low"}


def test_the_cosine_band_does_not_depend_on_the_other_hits():
    """An absolute scale is the whole point: the same passage scores the
    same whatever it is shown beside."""
    hit = a_hit(dense_score=0.70)

    alone = relevance(hit, basis="cosine", model=_CALIBRATED, best=0.70)
    beside = relevance(hit, basis="cosine", model=_CALIBRATED, best=0.99)

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

    assert relevance(best, basis="lexical", model=None, best=20.0) == "very high"
    assert relevance(middling, basis="lexical", model=None, best=20.0) == "medium"
    assert relevance(poor, basis="lexical", model=None, best=20.0) == "very low"


def test_the_best_lexical_hit_is_always_the_top_band():
    """By construction, which is exactly why `relevance_phrase` has to say
    the band is relative."""
    for best in (0.1, 5.0, 900.0):
        hit = a_hit(bm25_score=best)
        assert relevance(hit, basis="lexical", model=None, best=best) == "very high"


def test_a_band_needs_a_score_on_the_leg_it_bands():
    """A hybrid hit found only by the lexical leg has no cosine. Saying
    nothing is correct; inventing one is not."""
    assert relevance(a_hit(), basis="cosine", model=_CALIBRATED, best=0.8) is None
    assert relevance(a_hit(), basis="lexical", model=None, best=1.0) is None


def test_a_zero_best_score_does_not_divide_by_zero():
    hit = a_hit(bm25_score=0.0)

    assert relevance(hit, basis="lexical", model=None, best=0.0) is not None


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
