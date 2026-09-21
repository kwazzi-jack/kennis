"""Lexical retrieval, and the refusal to build an index over nothing.

The index is kept aligned to the same ordered chunk list used everywhere
else, so a retrieved rank is a position in that list and maps straight back
to a chunk without storing anything twice. This is also the pure-text path: a
collection can be searched with only this index and no embeddings at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import bm25s

from kennis.engine.errors import NothingToIndex

_STOPWORDS: Final = "english"


class Bm25Index:
    """A persisted bm25s index over an ordered list of chunk texts."""

    def __init__(self, retriever: bm25s.BM25, count: int) -> None:
        self._retriever = retriever
        self._count = count

    @classmethod
    def build(cls, texts: list[str]) -> Bm25Index:
        """Index `texts`, or refuse if there is nothing in them to index.

        **The guard runs before bm25s is asked to index, not around it.** The
        failure it replaces is `ValueError: max() iterable argument is empty`
        from inside the vocabulary build, but three `RuntimeWarning`s fire
        first - a mean over an empty slice, then two divisions by zero - and
        under `filterwarnings = ["error"]` one of those is what a caller would
        actually see. Catching the `ValueError` would not have worked.

        The condition is that the vocabulary is empty, not that `texts` is:
        stopwords are removed before the vocabulary is built, so a collection
        whose documents are all stopwords fails in exactly the same place as
        an empty one. Checking the tokenised vocabulary catches both, and
        catches them for the reason that is actually true.
        """
        tokens = bm25s.tokenize(texts, stopwords=_STOPWORDS, show_progress=False)
        if not getattr(tokens, "vocab", None):
            raise NothingToIndex(
                "this collection is empty: there is no text to index"
                if not texts
                else "this collection has no indexable words in it"
            )

        retriever = bm25s.BM25()
        retriever.index(tokens, show_progress=False)
        return cls(retriever, len(texts))

    @classmethod
    def load(cls, directory: Path | str, count: int) -> Bm25Index:
        """An index read back from `directory`.

        `count` is supplied rather than read back because the corpus is not
        stored alongside the index - the ordered chunk list lives beside it
        and is what a rank indexes into.
        """
        retriever = bm25s.BM25.load(str(directory), load_corpus=False)
        return cls(retriever, count)

    def save(self, directory: Path | str) -> None:
        self._retriever.save(str(directory))

    def retrieve(self, query: str, k: int) -> list[tuple[int, float]]:
        """Up to `k` `(chunk_index, score)` pairs, best first."""
        if self._count == 0:
            return []
        wanted = min(k, self._count)
        query_tokens = bm25s.tokenize(query, stopwords=_STOPWORDS, show_progress=False)
        indices, scores = self._retriever.retrieve(
            query_tokens, k=wanted, show_progress=False
        )
        return [
            (int(index), float(score))
            for index, score in zip(indices[0], scores[0], strict=True)
            # A query whose words are not in the vocabulary still fills `k`
            # slots, scored zero. Those are not hits and must not be returned
            # as if they were.
            if score > 0.0
        ]
