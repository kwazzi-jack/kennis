"""One search hit, as a person reads it.

**A relevance band is a claim on a scale, and most of the numbers a search
carries have no scale to make it on.** `SearchResult.score` is the
reciprocal-rank-fusion value, `sum 1 / (60 + rank)` over the legs that ran:
it is a function of rank and of nothing else, so banding it restates the
ordering the list already shows and would label a hit that matched nothing
"very high" for being first. `bm25_score` is unbounded and corpus-relative.
Only the cosine of a dense hit has an absolute meaning, and only for the
model that produced it.

So there are two bands and a silence:

- **cosine**, against cuts measured for one model on a real corpus;
- **lexical**, a fraction of the best hit of the same query, for a search
  with no dense leg - relative, and the phrasing says so;
- **nothing at all** for a dense search on a model kennis has not measured,
  because inventing cuts for an unknown scale is the failure both of the
  above avoid.

The cuts are in `_COSINE_CUTS` with the run that produced them. Concerns
#186 and #198.
"""

from __future__ import annotations

from typing import Final, Literal

from kennis.engine.rag.models import SearchResult

type Relevance = Literal["very high", "high", "medium", "low", "very low"]
type Basis = Literal["cosine", "lexical"]
type ScoreStyle = Literal["human", "raw", "none"]

SCORE_STYLES: Final[tuple[str, ...]] = ("human", "raw", "none")

_LEVELS: Final[tuple[Relevance, ...]] = (
    "very high",
    "high",
    "medium",
    "low",
    "very low",
)

# Four cuts, four boundaries between the five levels above.
#
# Measured on 2026-09-23 over 243 chunks of a real corpus with nine queries,
# five meaningful and four deliberate nonsense. The model's scores occupy
# roughly [0.37, 0.82] rather than [0, 1], and the separation that matters
# is between the best hits of the two kinds of query: 0.765 to 0.816 for the
# real ones, 0.567 to 0.607 for the nonsense, with nothing in between. These
# cuts put the first group in `high` and `very high` and the second in `low`.
#
# A model missing from this table gets no band. The numbers describe the
# model, not kennis, and a different embedding model puts its scores
# somewhere else entirely.
_COSINE_CUTS: Final[dict[str, tuple[float, float, float, float]]] = {
    "BAAI/bge-small-en-v1.5": (0.80, 0.72, 0.64, 0.56),
}

CALIBRATED_MODELS: Final[frozenset[str]] = frozenset(_COSINE_CUTS)

# The lexical band's cuts, as fractions of the query's own best hit. Wider
# than the cosine ones because BM25 scores spread across an order of
# magnitude within one result list, where cosines are packed into a tenth.
_LEXICAL_CUTS: Final[tuple[float, float, float, float]] = (0.8, 0.6, 0.4, 0.2)


def basis_for(model: str | None, *, dense_ran: bool) -> Basis | None:
    """Which scale this search's hits can be banded on, if any.

    `model` is the embedding model the *index* was built with, read back
    from its binding rather than from the current configuration - the same
    rule the query embedding follows, and for the same reason.
    """
    if not dense_ran:
        return "lexical"
    if model is not None and model in _COSINE_CUTS:
        return "cosine"
    return None


def relevance(
    result: SearchResult, *, basis: Basis, model: str | None, best: float
) -> Relevance | None:
    """How well this passage matched, or None when the leg did not score it.

    A hybrid hit found by the lexical leg alone carries no cosine. Saying
    nothing about it is correct, and a band derived from the other leg would
    be a different measurement wearing the same word.
    """
    if basis == "cosine":
        if result.dense_score is None or model is None:
            return None
        return _banded(result.dense_score, _COSINE_CUTS[model])
    if result.bm25_score is None:
        return None
    # An all-zero result list is not a ranking; every hit is as good as the
    # best one, which is what a fraction of zero should mean and what a
    # division would instead refuse to say.
    share = 1.0 if best == 0 else result.bm25_score / best
    return _banded(share, _LEXICAL_CUTS)


def _banded(value: float, cuts: tuple[float, float, float, float]) -> Relevance:
    # Four cuts against the first four levels; the fifth is what is left
    # below all of them, so it is returned rather than paired.
    for level, cut in zip(_LEVELS[:-1], cuts, strict=True):
        if value >= cut:
            return level
    return _LEVELS[-1]


def relevance_phrase(basis: Basis) -> str:
    """What the band on these hits is a band of.

    Printed once per **group** rather than once per hit: it is a property of
    a collection's own search, and the lexical one in particular has to be
    read before the levels are, because its best hit is the top level by
    construction.

    It used to be printed once for the whole report, which was true only
    while every collection agreed - and the report dropped it entirely when
    they did not, which is the one case a reader needs it. Concern #230.
    """
    if basis == "cosine":
        return "relevance by cosine similarity"
    return "relevance relative to the best lexical match"


def hit_headline(rank: int, result: SearchResult) -> str:
    """The line a reader scans: what this hit is.

    The collection is not here. It is on the group heading above, printed
    once for every hit that shares it; carrying it on each line was what a
    merged list of three collections needed, and there is no merged list any
    more. Concern #231.

    The identifier is not here either. It is on the handle line below, with
    the chunk index it has to travel with, because the pair is what
    `kennis read` takes and splitting them across two lines invites copying
    one without the other.
    """
    chunk = result.chunk
    title = str(chunk.metadata.get("title") or chunk.document_id)
    section = chunk.section if chunk.section != title else None
    where = f" - {section}" if section else ""
    return f"[{rank}] {title}{where}"


def hit_handle(result: SearchResult) -> str:
    """The coordinates `kennis read` takes, as `key=value` pairs.

    `id` and `chunk` rather than `document_id` and `chunk_index`: they are
    the words the command's own option uses (`--chunk`), and the line is
    read beside a command, not beside the schema.
    """
    return f"id={result.chunk.document_id} chunk={result.chunk.chunk_index}"


def raw_scores(result: SearchResult) -> str:
    """Every leg that ran, at the precision that distinguishes hits.

    Four decimals on the fused score because RRF differences between
    adjacent ranks are in the fourth; three on a cosine, which is packed
    into a tenth of its range; two on BM25, which is not.

    A leg that did not run is omitted rather than shown as zero, which would
    read as "ran and found nothing".
    """
    parts = [f"rrf={result.score:.4f}"]
    if result.bm25_score is not None:
        parts.append(f"bm25={result.bm25_score:.2f}")
    if result.dense_score is not None:
        parts.append(f"cos={result.dense_score:.3f}")
    return " ".join(parts)


__all__ = [
    "CALIBRATED_MODELS",
    "SCORE_STYLES",
    "Basis",
    "Relevance",
    "ScoreStyle",
    "basis_for",
    "hit_handle",
    "hit_headline",
    "raw_scores",
    "relevance",
    "relevance_phrase",
]
