"""Meaning graded against unrelated questions, for an unmeasured model (#599).

For each collection, every anchor question's best cosine is taken, and the
reference is the second highest of them (Brian, 2026-11-01): a hit above it
is closer to the question than all but one unrelated question came to
anything in the collection.
"""

from __future__ import annotations

import numpy as np
import pytest

from kennis.engine.rag import anchors
from kennis.engine.rag.anchors import (
    ANCHOR_QUESTIONS,
    reference_of,
    unrelated_reference,
)
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.bm25 import Bm25Index
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding
from kennis.engine.rag.index import LoadedIndex
from kennis.engine.rag.models import Chunk, SearchResult
from kennis.render.hits import Hit, relevance_phrase, relevances, score_style_for


def test_the_reference_is_the_second_highest_best():
    assert reference_of([0.2, 0.9, 0.5, 0.7]) == 0.7
    assert reference_of([0.4, 0.4]) == 0.4


def test_a_reference_needs_two_anchors():
    with pytest.raises(ValueError):
        reference_of([0.3])


def test_there_are_twenty_anchors_each_its_own():
    assert len(ANCHOR_QUESTIONS) == 20
    assert len(set(ANCHOR_QUESTIONS)) == 20


class AxisEmbedder:
    """Anchor `n` along axis `n`; any other text along the last axis."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        width = len(ANCHOR_QUESTIONS) + 1
        rows = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            axis = (
                ANCHOR_QUESTIONS.index(text) if text in ANCHOR_QUESTIONS else width - 1
            )
            rows[row, axis] = 1.0
        return rows


def an_index(matrix: np.ndarray, *, model: str = "unmeasured-model") -> LoadedIndex:
    return LoadedIndex(
        collection="notes",
        chunks=[],
        bm25=Bm25Index.build(["a passage"]),
        binding=Binding(
            chunking=ChunkParameters(),
            model=ModelBinding(kind="fastembed", model=model),
        ),
        matrix=matrix,
    )


@pytest.fixture(autouse=True)
def nothing_cached() -> None:
    anchors.forget_anchor_vectors()


def test_the_reference_is_read_from_the_collection_s_own_chunks():
    """Three chunks: one lies along anchor 0 at 0.9, one along anchor 1 at
    0.6, one along anchor 2 at 0.3. Anchor bests are 0.9, 0.6, 0.3 and zero
    for the rest, so the second highest is 0.6."""
    width = len(ANCHOR_QUESTIONS) + 1
    matrix = np.zeros((3, width), dtype=np.float32)
    for row, (axis, value) in enumerate([(0, 0.9), (1, 0.6), (2, 0.3)]):
        matrix[row, axis] = value
        matrix[row, width - 1] = np.sqrt(1 - value**2)

    reference = unrelated_reference(
        an_index(matrix), host=None, embedder=AxisEmbedder()
    )

    assert reference == pytest.approx(0.6)


def test_the_anchors_are_embedded_once_per_model():
    width = len(ANCHOR_QUESTIONS) + 1
    matrix = np.eye(width, dtype=np.float32)
    embedder = AxisEmbedder()

    unrelated_reference(an_index(matrix), host=None, embedder=embedder)
    unrelated_reference(an_index(matrix), host=None, embedder=embedder)
    unrelated_reference(an_index(matrix, model="another"), host=None, embedder=embedder)

    assert embedder.calls == 2


def test_a_lexical_index_has_no_reference():
    index = an_index(np.zeros((0, 0), dtype=np.float32))
    assert unrelated_reference(index, host=None, embedder=AxisEmbedder()) is None
    lexical = LoadedIndex(
        collection="notes",
        chunks=[],
        bm25=Bm25Index.build(["a passage"]),
        binding=Binding(chunking=ChunkParameters(), model=None),
        matrix=None,
    )
    assert unrelated_reference(lexical, host=None, embedder=AxisEmbedder()) is None


# --- the levels it gives ---------------------------------------------------


def a_result(*, dense: float | None, bm25: float | None = None) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            id="d::0",
            collection="notes",
            document_id="d",
            chunk_index=0,
            text="text",
            source_path="notes/d.md",
            char_start=0,
            char_end=4,
        ),
        score=0.03,
        bm25_score=bm25,
        dense_score=dense,
    )


@pytest.mark.parametrize(
    ("cosine", "level"),
    [(0.41, "above unrelated"), (0.40, "unrelated"), (0.12, "unrelated")],
)
def test_an_unmeasured_model_is_graded_against_the_reference(cosine: float, level: str):
    found = relevances(
        a_result(dense=cosine), model="text-embedding-3-small", best=1.0, unrelated=0.40
    )

    assert found == (("meaning", level),)


def test_a_measured_model_keeps_its_five_levels():
    found = relevances(
        a_result(dense=0.70),
        model="text-embedding-3-large",
        best=1.0,
        unrelated=0.90,
    )

    assert found == (("meaning", "very high"),)


def test_without_a_reference_an_unmeasured_model_says_nothing_of_meaning():
    assert relevances(a_result(dense=0.9), model="unmeasured", best=1.0) == ()


def test_the_scale_is_named_for_what_it_was_graded_against():
    assert relevance_phrase({"meaning"}, meaning="unrelated") == (
        "meaning against unrelated questions"
    )
    assert relevance_phrase({"meaning"}) == "meaning as an absolute cosine"


def test_a_graded_hit_keeps_the_human_style():
    """A meaning level from the reference is a level: the search is not
    turned to raw numbers for want of a scale."""
    hits = [
        Hit(
            collection="notes",
            result=a_result(dense=0.5),
            model="unmeasured",
            unrelated=0.3,
        )
    ]

    assert score_style_for(hits, "human") == ("human", False)


# --- attached to a search's hits ------------------------------------------


def a_hit(model: str, *, dense: float | None) -> Hit:
    return Hit(collection="notes", result=a_result(dense=dense, bm25=1.0), model=model)


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each model the reference was asked for, answering 0.25."""
    models: list[str] = []

    def answered(index: LoadedIndex, *, host: str | None) -> float:
        assert index.binding.model is not None
        models.append(index.binding.model.model)
        return 0.25

    monkeypatch.setattr(anchors, "unrelated_reference", answered)
    return models


def test_an_unmeasured_model_s_hits_carry_the_reference(asked: list[str]):
    from kennis.retrieval import with_unrelated_reference

    index = an_index(np.eye(3, dtype=np.float32), model="text-embedding-3-small")
    hits = with_unrelated_reference(
        [a_hit("text-embedding-3-small", dense=0.4)], index, host=None
    )

    assert [hit.unrelated for hit in hits] == [0.25]
    assert asked == ["text-embedding-3-small"]


def test_a_measured_model_s_hits_are_not_asked_about(asked: list[str]):
    from kennis.retrieval import with_unrelated_reference

    index = an_index(np.eye(3, dtype=np.float32), model="text-embedding-3-large")
    hits = with_unrelated_reference(
        [a_hit("text-embedding-3-large", dense=0.4)], index, host=None
    )

    assert [hit.unrelated for hit in hits] == [None]
    assert asked == []


def test_hits_the_meaning_leg_did_not_score_are_not_asked_about(asked: list[str]):
    from kennis.retrieval import with_unrelated_reference

    index = an_index(np.eye(3, dtype=np.float32))
    hits = with_unrelated_reference([a_hit("unmeasured", dense=None)], index, host=None)

    assert [hit.unrelated for hit in hits] == [None]
    assert asked == []


def test_anchors_that_cannot_be_embedded_cost_only_the_level(
    monkeypatch: pytest.MonkeyPatch,
):
    from kennis.engine.errors import KennisError
    from kennis.retrieval import with_unrelated_reference

    def refused(index: LoadedIndex, *, host: str | None) -> float:
        raise KennisError("the embedding service did not answer")

    monkeypatch.setattr(anchors, "unrelated_reference", refused)
    index = an_index(np.eye(3, dtype=np.float32))

    hits = with_unrelated_reference([a_hit("unmeasured", dense=0.4)], index, host=None)

    assert [hit.unrelated for hit in hits] == [None]


# --- what the scale is called --------------------------------------------


def a_graded(model: str, *, unrelated: float | None) -> Hit:
    return Hit(
        collection="notes",
        result=a_result(dense=0.5),
        model=model,
        unrelated=unrelated,
    )


def test_a_group_s_scale_is_the_one_its_hits_were_graded_on():
    from kennis.render.hits import meaning_scale_of

    measured = a_graded("text-embedding-3-large", unrelated=None)
    unmeasured = a_graded("text-embedding-3-small", unrelated=0.3)

    assert meaning_scale_of([measured]) == "cosine"
    assert meaning_scale_of([unmeasured]) == "unrelated"
    assert meaning_scale_of([measured, unmeasured]) == "both"


def test_the_window_s_key_names_only_measured_models():
    from kennis.gui.pages import shown_key
    from kennis.retrieval import Sweep

    found = Sweep(
        groups={
            "literature": [a_graded("text-embedding-3-large", unrelated=None)],
            "notes": [a_graded("text-embedding-3-small", unrelated=0.3)],
        },
        searched=("literature", "notes"),
        skipped=(),
        degraded=(),
    )

    key = shown_key(found)

    assert key is not None
    assert key.models == ("text-embedding-3-large",)
    meaning = [line for line in key.lines if line.label == "meaning"]
    assert [line.scale for line in meaning] == [
        "meaning as an absolute cosine or against unrelated questions"
    ]


def test_a_group_graded_against_unrelated_questions_says_so():
    from kennis.render.hits import basis_phrase

    hits = [a_graded("text-embedding-3-small", unrelated=0.3)]

    assert basis_phrase(hits, "human") == "meaning against unrelated questions"
