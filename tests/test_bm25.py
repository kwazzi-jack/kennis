"""The lexical index, and its refusal to be built over nothing.

BM25 is kept aligned to the same ordered chunk list used everywhere else, so
a retrieved rank maps straight back to a chunk by integer index. It is also
the pure-text path: a collection can be searched with only this index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import NothingToIndex
from kennis.engine.rag.bm25 import Bm25Index

TEXTS = [
    "The radio interferometer measurement equation describes visibilities.",
    "Calibration solves for antenna gains against a sky model.",
    "Deconvolution reconstructs an image from the dirty map.",
]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_a_query_returns_the_chunk_that_holds_its_words():
    index = Bm25Index.build(TEXTS)

    hits = index.retrieve("antenna gains calibration", k=3)

    assert hits
    assert hits[0][0] == 1


def test_hits_come_back_best_first():
    index = Bm25Index.build(TEXTS)

    scores = [score for _, score in index.retrieve("image deconvolution", k=3)]

    assert scores == sorted(scores, reverse=True)


def test_a_rank_is_an_index_into_the_list_that_was_indexed():
    """The whole reason the chunk list stays ordered: a rank is a position,
    so nothing has to be stored twice to map a hit back to its chunk."""
    index = Bm25Index.build(TEXTS)

    for position, _ in index.retrieve("visibilities", k=3):
        assert 0 <= position < len(TEXTS)


def test_asking_for_more_than_there_is_returns_what_there_is():
    index = Bm25Index.build(TEXTS)

    assert len(index.retrieve("calibration", k=50)) <= len(TEXTS)


def test_a_query_matching_nothing_returns_nothing_rather_than_failing():
    index = Bm25Index.build(TEXTS)

    assert index.retrieve("zzzzqqq", k=3) == []


# ---------------------------------------------------------------------------
# Refusing to index nothing
# ---------------------------------------------------------------------------


def test_an_empty_collection_is_refused_with_a_message_about_the_collection():
    """Without the guard this is `ValueError: max() iterable argument is
    empty` from inside the vocabulary build, which names nothing the user
    can act on."""
    with pytest.raises(NothingToIndex) as raised:
        Bm25Index.build([])

    assert "empty" in str(raised.value).lower()


def test_the_refusal_names_the_command_that_resolves_it():
    with pytest.raises(NothingToIndex) as raised:
        Bm25Index.build([])

    assert any("kennis corpus add" in note for note in raised.value.__notes__)


def test_a_collection_of_nothing_but_stopwords_is_refused_too():
    """The condition is not 'no documents', it is 'no tokens survived
    tokenisation'. Stopwords are removed before the vocabulary is built, so
    these fail in exactly the same place as an empty list."""
    with pytest.raises(NothingToIndex):
        Bm25Index.build(["the and of", "it is a"])


def test_a_single_empty_document_is_refused():
    with pytest.raises(NothingToIndex):
        Bm25Index.build([""])


def test_one_indexable_document_among_empty_ones_is_enough():
    """The guard refuses a corpus with no vocabulary at all, not a corpus
    with a thin document in it."""
    index = Bm25Index.build(["", "calibration solves for gains", ""])

    assert index.retrieve("calibration", k=3)[0][0] == 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_an_index_survives_a_save_and_a_load(tmp_path: Path):
    directory = tmp_path / "bm25"
    Bm25Index.build(TEXTS).save(directory)

    reloaded = Bm25Index.load(directory, count=len(TEXTS))

    assert reloaded.retrieve("antenna gains", k=3)[0][0] == 1


def test_a_reloaded_index_ranks_identically(tmp_path: Path):
    directory = tmp_path / "bm25"
    built = Bm25Index.build(TEXTS)
    built.save(directory)

    reloaded = Bm25Index.load(directory, count=len(TEXTS))

    assert built.retrieve("image", k=3) == reloaded.retrieve("image", k=3)
