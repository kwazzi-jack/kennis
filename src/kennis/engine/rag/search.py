"""Ranked search over a built index.

Two retrievers run over one ordered chunk list and are combined by
**reciprocal rank fusion**: a chunk scores `sum 1 / (k + rank)` over the
lists it appears in, and only its position in each list is used.

Fusing positions rather than scores is the whole point. BM25 returns an
unbounded, corpus-relative term score; cosine similarity returns a number in
`[-1, 1]`. Normalising one onto the other means knowing both distributions,
which change with every build. Positions need no such knowledge, and with one
retriever available the result is simply that retriever's ordering - so a
lexical-only index, or a query with no lexical overlap, degrades cleanly
rather than as a special case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import numpy as np

from kennis.engine.errors import SearchUnavailable
from kennis.engine.rag.embedding import Embedder, embed_texts
from kennis.engine.rag.index import LoadedIndex
from kennis.engine.rag.models import (
    Chunk,
    ChunkPredicate,
    Filter,
    Metadata,
    SearchResult,
    combine_filters,
)

type Mode = Literal["hybrid", "dense", "bm25"]

# `score = sum 1 / (RRF_K + rank)`. The constant from the original paper; it
# flattens the difference between adjacent high ranks, so being first in one
# list is worth less than appearing in both.
_RRF_K: Final = 60

# How many each leg retrieves before fusion. Retrieving only `top_k` from
# each would give at most `top_k` distinct chunks and waste the fusion: the
# case it exists for is a chunk ranked eighth by one leg and fortieth by the
# other rising above one ranked second by a single leg.
_CANDIDATES: Final = 50

_DEFAULT_TOP_K: Final = 10


@dataclass(frozen=True, slots=True)
class DocumentSpan:
    """A contiguous run of one document's chunks, stitched back into text.

    Every coordinate here is one search also surfaces, so a hit's
    `document_id` and `chunk_index` go straight back into a read request.
    """

    document_id: str
    source_path: str
    chunk_start: int
    chunk_end: int
    char_start: int
    char_end: int
    sections: list[str]
    text: str
    metadata: Metadata


def search(
    index: LoadedIndex,
    question: str,
    *,
    top_k: int = _DEFAULT_TOP_K,
    filters: list[Filter] | None = None,
    mode: Mode = "hybrid",
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """The best `top_k` chunks for `question`, best first.

    **The query is embedded with the index's own binding**, read back from
    the index rather than taken from the caller's current configuration. A
    query vector computed with a different model is meaningless against these
    rows, and would not error - it would return confident nonsense.

    `filters` are applied to each leg's candidate list before fusion. That is
    the cheap choice, and it has a consequence worth knowing: a filter
    selective enough that its matches rank below the candidate window returns
    fewer results than exist, or none. Nothing false is returned; the answer
    is incomplete rather than wrong.
    """
    if mode in ("hybrid", "dense") and index.matrix is None:
        raise SearchUnavailable(
            f"the '{index.collection}' index was built without an embedding "
            f"backend, so it has no dense leg to run a '{mode}' search against; "
            "search it with mode 'bm25' instead"
        )

    predicate = combine_filters(filters)
    candidates = max(top_k, _CANDIDATES)

    dense_ranks, dense_scores = (
        _dense_leg(index, question, candidates, predicate, embedder)
        if mode in ("hybrid", "dense")
        else ([], {})
    )
    bm25_ranks, bm25_scores = (
        _bm25_leg(index, question, candidates, predicate)
        if mode in ("hybrid", "bm25")
        else ([], {})
    )

    return [
        SearchResult(
            chunk=index.chunks[position],
            score=score,
            dense_rank=_rank_of(position, dense_ranks),
            bm25_rank=_rank_of(position, bm25_ranks),
            bm25_score=bm25_scores.get(position),
            dense_score=dense_scores.get(position),
        )
        for position, score in _fuse(dense_ranks, bm25_ranks)[:top_k]
    ]


def read_span(
    index: LoadedIndex,
    document_id: str,
    *,
    chunk_index: int = 0,
    before: int = 1,
    after: int = 1,
) -> DocumentSpan:
    """The text around one chunk, stitched back into a continuous run.

    A hit is one chunk and a reader usually wants what surrounds it.
    """
    chunks = sorted(
        (chunk for chunk in index.chunks if chunk.document_id == document_id),
        key=lambda chunk: chunk.chunk_index,
    )
    if not chunks:
        raise SearchUnavailable(
            f"'{document_id}' is not in the '{index.collection}' index",
            resolution=f"kennis corpus index --collection {index.collection}",
        )

    positions = {chunk.chunk_index: position for position, chunk in enumerate(chunks)}
    anchor = positions.get(chunk_index, 0)
    run = chunks[max(0, anchor - before) : anchor + after + 1]

    return DocumentSpan(
        document_id=document_id,
        source_path=run[0].source_path,
        chunk_start=run[0].chunk_index,
        chunk_end=run[-1].chunk_index,
        char_start=run[0].char_start,
        char_end=run[-1].char_end,
        sections=list(
            dict.fromkeys(chunk.section for chunk in run if chunk.section is not None)
        ),
        text=_stitch(run),
        metadata=dict(run[0].metadata),
    )


def _dense_leg(
    index: LoadedIndex,
    question: str,
    candidates: int,
    predicate: ChunkPredicate | None,
    embedder: Embedder | None,
) -> tuple[list[int], dict[int, float]]:
    """The nearest chunks by cosine similarity, filtered.

    **This leg has no notion of "no match".** Cosine similarity is defined
    for every pair, so the nearest `candidates` chunks always exist however
    unrelated they are, and fusion weights them by position rather than by
    closeness. A query about nothing in the corpus still returns its nearest
    neighbours. No threshold is applied, because any value would be arbitrary
    - but it is why a nonsense query returns confident-looking results.
    """
    matrix = index.matrix
    if matrix is None or matrix.shape[0] == 0 or index.binding.model is None:
        return [], {}

    vector = embed_texts(
        index.binding.model, [question], embedder=embedder, batch_size=1
    )[0]
    norm = float(np.linalg.norm(vector)) or 1.0
    scores = matrix @ (vector / norm)
    order = [int(position) for position in np.argsort(-scores)[:candidates]]
    kept = _kept(order, index.chunks, predicate)
    return kept, {position: float(scores[position]) for position in kept}


def _bm25_leg(
    index: LoadedIndex,
    question: str,
    candidates: int,
    predicate: ChunkPredicate | None,
) -> tuple[list[int], dict[int, float]]:
    hits = [
        (position, score)
        for position, score in index.bm25.retrieve(question, candidates)
        if predicate is None or predicate(index.chunks[position])
    ]
    return [position for position, _ in hits], dict(hits)


def _kept(
    order: list[int], chunks: list[Chunk], predicate: ChunkPredicate | None
) -> list[int]:
    if predicate is None:
        return order
    return [position for position in order if predicate(chunks[position])]


def _fuse(*rank_lists: list[int]) -> list[tuple[int, float]]:
    """Fuse ranked position lists into `(position, score)`, best first."""
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for offset, position in enumerate(ranks):
            scores[position] = scores.get(position, 0.0) + 1.0 / (_RRF_K + offset + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def _rank_of(position: int, ranks: list[int]) -> int | None:
    """The one-based place of `position` in `ranks`, or None if absent."""
    try:
        return ranks.index(position) + 1
    except ValueError:
        return None


def _stitch(chunks: list[Chunk]) -> str:
    """Document-ordered chunks concatenated into continuous text.

    Chunks overlap by design and their offsets index the original exactly, so
    a plain concatenation repeats text. Appending only the part of each chunk
    past what is already covered reconstructs the original; a gap where the
    chunker skipped whitespace is bridged with a newline, so two paragraphs
    do not fuse into one.
    """
    parts: list[str] = []
    covered_to = -1
    for chunk in chunks:
        if chunk.char_start >= covered_to:
            if parts and chunk.char_start > covered_to:
                parts.append("\n")
            parts.append(chunk.text)
        elif chunk.char_end > covered_to:
            parts.append(chunk.text[covered_to - chunk.char_start :])
        covered_to = max(covered_to, chunk.char_end)
    return "".join(parts)
