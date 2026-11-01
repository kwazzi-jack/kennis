"""How close an unrelated question comes to a collection (#599).

A cosine means something only on its model's scale, and kennis has measured
the scale of two models (`render/hits.py::_COSINE_CUTS`). For any other, a
hit is graded against what unrelated questions reach in the same
collection: each of twenty fixed anchor questions is embedded with the
index's model, its best cosine against the collection's chunks is taken,
and the reference is the **second highest** of those twenty.

Why the second highest (Brian, 2026-11-01): if a new unrelated question
behaves as one more anchor, the chance its best hit exceeds the k-th
highest of n anchors is k / (n + 1), so 2/21, about one in ten; and kennis
knows nothing about its subject, so one anchor may touch the corpus - a
cooking corpus and the bread question - and the maximum would then put
every hit under it. The maximum would be one in twenty-one, and fragile.

Why it is a stopgap: two levels, "unrelated" and "above unrelated", are all
an unrelated floor can say. A model's full scale needs real questions as
well, which is the measurement `_COSINE_CUTS` records; doing that for any
model, on the reader's own corpus, is a future feature (#600).

**Nothing is written.** The anchors' vectors are kept in this process for
each model - one batched request, once per service start - and the
reference is computed from the index already loaded for the search, so no
index needs rebuilding.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Final

import numpy as np

from kennis.engine.rag.embedding import (
    Embedder,
    ModelBinding,
    embed_texts,
    reachable_model,
)
from kennis.engine.rag.index import LoadedIndex

# Everyday subjects, each far from the others, so that one corpus can touch
# one or two of them and not the rest. Never change one without measuring:
# the reference is their statistic.
ANCHOR_QUESTIONS: Final[tuple[str, ...]] = (
    "banana bread recipe with walnuts",
    "the offside rule in association football",
    "how to tune a violin by ear",
    "medieval castle defensive architecture",
    "best houseplants for a dark apartment",
    "tax return deadlines for freelancers",
    "how to remove a red wine stain from a carpet",
    "training a puppy to walk on a lead",
    "the plot of a famous romantic comedy film",
    "choosing running shoes for flat feet",
    "how to knit a scarf for beginners",
    "booking cheap train tickets across Europe",
    "symptoms of the common cold in children",
    "repotting an orchid after it flowers",
    "rules of the card game bridge",
    "how to brew coffee with a French press",
    "planning a wedding on a small budget",
    "changing a flat tyre on a bicycle",
    "the history of the Roman colosseum",
    "folding a fitted bed sheet neatly",
)

_LOCK: Final = threading.Lock()
_VECTORS: dict[tuple[str, str, str | None], np.ndarray] = {}


def reference_of(bests: Sequence[float]) -> float:
    """The second highest of the anchors' best cosines."""
    if len(bests) < 2:
        raise ValueError("a reference needs at least two anchors")
    return sorted(bests, reverse=True)[1]


def unrelated_reference(
    index: LoadedIndex, *, host: str | None, embedder: Embedder | None = None
) -> float | None:
    """The reference cosine for this index's collection, or None for an
    index with no vectors."""
    matrix = index.matrix
    model = index.binding.model
    if matrix is None or matrix.shape[0] == 0 or model is None:
        return None
    vectors = _anchor_vectors(reachable_model(model, host=host), embedder)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    scores = matrix @ (vectors / norms).T
    return reference_of([float(value) for value in scores.max(axis=0)])


def _anchor_vectors(model: ModelBinding, embedder: Embedder | None) -> np.ndarray:
    key = (model.kind, model.model, model.host)
    with _LOCK:
        held = _VECTORS.get(key)
    if held is not None:
        return held
    vectors = embed_texts(model, list(ANCHOR_QUESTIONS), embedder=embedder)
    with _LOCK:
        _VECTORS[key] = vectors
    return vectors


def forget_anchor_vectors() -> None:
    """Empty the per-process cache; for a test that counts requests."""
    with _LOCK:
        _VECTORS.clear()


__all__ = [
    "ANCHOR_QUESTIONS",
    "forget_anchor_vectors",
    "reference_of",
    "unrelated_reference",
]
