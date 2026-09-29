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

- **meaning**, the cosine against cuts measured for one model on a real
  corpus - absolute, and only for a model kennis has measured;
- **lexical**, a fraction of the best hit of the same query in the same
  collection - relative, and the label says so;
- **nothing at all** for a leg that did not score, and no meaning band at
  all on a model kennis has not measured, because inventing cuts for an
  unknown scale is the failure both of the above avoid.

**Each leg answers for itself, and that is a correction.** This module
used to reason all of the above correctly and then resolve it by choosing
*one* band: `basis_for` returned `cosine` whenever a dense leg ran on a
calibrated model, so under hybrid search BM25 never spoke. A one-word
query embeds to a modest cosine against a full chunk, so a search for
`selfcal` that highlighted the literal word in the passage reported
`relevance: low`. The reasoning was right about the hard part - the two
scales mean different things and must not be conflated - and the
resolution should have been to show both, labelled, rather than to pick.
Concern #379.

Nothing about *ordering* changes here. Hits are fused by reciprocal rank,
so a hit reading `lexical: very high  meaning: low` can sit below one
reading `lexical: high  meaning: medium`. That is what fusion did, and it
is what the single band was hiding.

The cuts are in `_COSINE_CUTS` with the run that produced them. Concerns
#186, #198 and #379.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from kennis.engine.context.bundle import BUNDLE_DIRNAME
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.rag.models import SearchResult
from kennis.render.words import snippet_of

type Relevance = Literal["very high", "high", "medium", "low", "very low"]

# The two legs a search can run, named for what they measure rather
# than for how. "lexical" is the engine's own word and this interface
# is read by researchers; "meaning" is what a cosine is *for*, where
# "dense" and "embedding" name the mechanism. First is lexical,
# because it is the one a reader can check by eye against the passage
# in front of them.
type Leg = Literal["lexical", "meaning"]

LEGS: Final[tuple[Leg, ...]] = ("lexical", "meaning")
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


def relevances(
    result: SearchResult, *, model: str | None, best: float
) -> tuple[tuple[Leg, Relevance], ...]:
    """One band per leg that actually scored this passage.

    Empty when neither did, which is a different thing from a band of
    "very low" and has to read differently.

    **A leg that did not run contributes nothing, and nothing has to
    ask whether it ran.** That falls out of its score being `None`,
    which is why there is no longer a `basis_for`: it existed to
    choose between the two scales, and there is no choice to make.

    `model` is the embedding model the *index* was built with, read back
    from its binding rather than from the current configuration - the same
    rule the query embedding follows, and for the same reason. Each
    collection has its own index and so possibly its own model, which is
    why it arrives per hit.
    """
    found: list[tuple[Leg, Relevance]] = []
    if result.bm25_score is not None:
        # An all-zero result list is not a ranking; every hit is as good as
        # the best one, which is what a fraction of zero should mean and
        # what a division would instead refuse to say.
        share = 1.0 if best == 0 else result.bm25_score / best
        found.append(("lexical", _banded(share, _LEXICAL_CUTS)))
    if result.dense_score is not None and model is not None and model in _COSINE_CUTS:
        found.append(("meaning", _banded(result.dense_score, _COSINE_CUTS[model])))
    return tuple(found)


def _banded(value: float, cuts: tuple[float, float, float, float]) -> Relevance:
    # Four cuts against the first four levels; the fifth is what is left
    # below all of them, so it is returned rather than paired.
    for level, cut in zip(_LEVELS[:-1], cuts, strict=True):
        if value >= cut:
            return level
    return _LEVELS[-1]


# One clause per leg, each naming the leg and then the scale its
# levels are on. The contrast the two clauses draw is the whole point:
# the lexical band moves if a better match arrives in this collection,
# the meaning band does not.
#
# **Noun phrases, not sentences**, because both front ends print this
# after the collection's name and "Notes meaning is an absolute
# cosine" reads as a possessive. The command line colours the name and
# a page does not, so only the page showed it. Concern #380.
_LEG_SCALES: Final[dict[Leg, str]] = {
    "lexical": "lexical as a fraction of the best match here",
    "meaning": "meaning as an absolute cosine",
}


def relevance_phrase(legs: Collection[Leg]) -> str:
    """What these bands are bands of, one clause per leg.

    Printed once per **group** rather than once per hit: it is a property of
    a collection's own search, and the lexical one in particular has to be
    read before the levels are, because its best hit is the top level by
    construction.

    It used to be printed once for the whole report, which was true only
    while every collection agreed - and the report dropped it entirely when
    they did not, which is the one case a reader needs it. Concern #230.

    It also used to refuse when a group carried two scales, on the ground
    that one sentence could not describe both. That was a consequence of
    there being one band to describe; with a label on each, two clauses
    describe two scales and mixing is the ordinary case. Concern #379.

    **`legs` is a collection, not a sequence, because the order is this
    function's and not its caller's.** The caller used to sort by
    `LEGS.index` first, which put the same rule in two places - and a
    rule enforced twice is a rule whose removal from either place
    cannot be observed. Concern #379.
    """
    return ", ".join(_LEG_SCALES[leg] for leg in LEGS if leg in legs)


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
    # Casefolded, because a title taken from a filename beside an H1
    # written in prose case - `calibration` and `Calibration` - is the
    # ordinary relationship between the two, not an odd one. A heading
    # that differs from the title only in case carries nothing the title
    # does not. Concern #296.
    same = chunk.section is not None and chunk.section.casefold() == title.casefold()
    section = None if same else chunk.section
    where = f" - {section}" if section else ""
    return f"[{rank}] {title}{where}"


def hit_handle(result: SearchResult) -> str:
    """The coordinates `kennis read` takes, as `key=value` pairs.

    `id` and `chunk` rather than `document_id` and `chunk_index`: they are
    the words the command's own option uses (`--chunk`), and the line is
    read beside a command, not beside the schema.
    """
    return f"id={result.chunk.document_id} chunk={result.chunk.chunk_index}"


def bundle_hit_handle(result: SearchResult, *, bundle_name: str) -> str:
    """Where a context hit is, which is the only handle it has.

    A corpus document is addressed by an identifier kennis minted and
    `kennis read` resolves. A bundle document is a file in the user's own
    project - the plan is explicit that there is no `read_context` - so the
    handle is the path, prefixed with the bundle's directory so it can be
    opened from the workspace root without working out where it lives.

    No chunk index, because there is no command here that takes a pair.
    """
    return f"path={bundle_name}/{result.chunk.document_id}"


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
    "LEGS",
    "SCORE_STYLES",
    "Leg",
    "Relevance",
    "ScoreStyle",
    "basis_phrase",
    "hit_detail_parts",
    "hit_handle",
    "hit_headline",
    "raw_scores",
    "relevance_phrase",
    "relevances",
]


@dataclass(frozen=True, slots=True)
class Hit:
    """One result, which collection produced it, and on what scale.

    The collection is carried alongside rather than read off the chunk,
    because a merged list is three lists interleaved and a reader has to
    be able to tell them apart without looking anything up.

    `model` travels with the hit rather than with the list because each
    collection has its own index and so its own embedding model: a corpus
    part-way through a model change can hold one index a relevance band
    is calibrated for and one it is not. `None` is "nothing here can be
    banded on meaning".

    There is no `basis`. It existed to choose which of the two scales a
    hit was banded on, and each leg now answers for itself. Concern
    #379.
    """

    collection: str
    result: SearchResult
    model: str | None


@dataclass(frozen=True, slots=True)
class RenderedHit:
    """One hit as text, in the three parts a reader sees.

    **Three fields rather than one string, and that is the seam design
    section 20 asks for.** The command line styles each part differently
    and indents the body; the MCP server joins them. The *text* is
    identical either way, which is what "the same bytes, one wearing
    ANSI" has to mean once one front end has colour and the other has
    none. A single joined string would force the command line to take
    the server's layout, and three separately rendered strings would let
    the two drift.

    `body` is None when no snippet was asked for, which is a different
    thing from an empty one.
    """

    headline: str
    detail: str
    # The same fields `detail` joins, for a front end whose layout has
    # to break between them. `detail` remains the byte-identical
    # string; a test asserts the two cannot drift. Concern #380.
    detail_parts: tuple[str, ...]
    body: str | None


_DETAIL_GAP: Final = "  "


def hit_detail_parts(hit: Hit, *, style: ScoreStyle, best: float) -> tuple[str, ...]:
    """How well a hit matched and how to reach it, one field per part.

    A context hit's handle is a path rather than an identifier, because
    a bundle document lives in the user's own project and there is no
    `read_context` to take a pair.

    **The parts rather than the line, because a narrow margin has to
    break between fields and cannot be trusted to find the break
    itself.** The window puts this in a monospace gutter about twenty
    characters wide; `white-space: pre-wrap` there preserved the two
    spaces but wrapped wherever the line ran out, so a second band
    arrived and split `meaning:` from `medium`. The join is still what
    the command line prints, byte for byte. Concern #380.
    """
    handle = (
        bundle_hit_handle(hit.result, bundle_name=BUNDLE_DIRNAME)
        if hit.collection == CONTEXT_COLLECTION
        else hit_handle(hit.result)
    )
    if style == "none":
        return (handle,)
    if style == "raw":
        return (raw_scores(hit.result), handle)
    found = relevances(hit.result, model=hit.model, best=best)
    return (*(f"{leg}: {level}" for leg, level in found), handle)


def hit_detail(hit: Hit, *, style: ScoreStyle, best: float) -> str:
    """The parts on one line, which is what a terminal shows.

    Two spaces between them, so the fields read as fields even where
    one of them contains a single space.
    """
    return _DETAIL_GAP.join(hit_detail_parts(hit, style=style, best=best))


def rendered_hit(
    hit: Hit, *, rank: int, style: ScoreStyle, best: float, snippet: str
) -> RenderedHit:
    """One hit, whole, as both front ends show it.

    The one place a hit becomes words. Section 20 calls this the
    deliberate exception to every front end rendering for itself, and
    says why it is worth the exception: the byte-identical property is
    what makes `kennis search` output a faithful proxy for what an agent
    sees, so a person debugging a retrieval problem at the terminal is
    looking at the thing the model looked at.
    """
    return RenderedHit(
        headline=hit_headline(rank, hit.result),
        detail=hit_detail(hit, style=style, best=best),
        detail_parts=hit_detail_parts(hit, style=style, best=best),
        body=(
            None
            if snippet == "none"
            else snippet_of(hit.result.chunk.text, full=snippet == "full")
        ),
    )


def basis_phrase(hits: Sequence[Hit], style: ScoreStyle) -> str:
    """What this group's relevance levels are bands of, or nothing.

    Empty when no level is being printed at all, so a report of raw
    scores does not carry a heading explaining a column it does not
    have, and empty when no hit in the group carries a band.

    It is **not** empty when a group carries both scales. That refusal
    was a consequence of there being one band; two labelled bands need
    two clauses, which is what they get. Concern #379.
    """
    if style != "human":
        return ""
    # Every leg any hit in the group has. A group where one hit was
    # found by both legs and another by one still needs both scales
    # explained, because both appear in the list.
    present = {
        leg
        for hit in hits
        for leg, _ in relevances(hit.result, model=hit.model, best=best_lexical(hits))
    }
    if not present:
        return ""
    return relevance_phrase(present)


def best_lexical(hits: Sequence[Hit]) -> float:
    """The best BM25 score in the list, which the lexical band is a fraction of.

    Within one collection, which is the only place a BM25 score is
    comparable. It used to be taken across all of them, because one
    column served every collection and a per-collection best would have
    made each collection's top hit "very high" with nothing to say so.
    Concern #231.
    """
    return max(
        (hit.result.bm25_score for hit in hits if hit.result.bm25_score is not None),
        default=0.0,
    )


def summary_of(groups: Mapping[str, Sequence[Hit]]) -> str:
    """`5 in docs, 2 in notes`: how much came from where.

    Which is the thing a grouped report can say and a merged one could
    not, and it is why the groups need no ranking between them - a
    reader sees the distribution before the first hit.

    The basis is not here. It belongs to a group, and this line spans
    them.
    """
    return ", ".join(f"{len(hits)} in {name}" for name, hits in groups.items())


def around(chunk_index: int) -> str:
    """The range that puts one chunk in context, as `--chunks` takes it.

    `max(0, ...)` is the part that matters: a hit at chunk 0 would
    otherwise print `-1:2`, and `-1` is the document's *last* chunk - so
    a printed command would send a reader to the wrong end of it.
    """
    return f"{max(0, chunk_index - 1)}:{chunk_index + 2}"


def score_style_for(hits: Sequence[Hit], asked: ScoreStyle) -> tuple[ScoreStyle, bool]:
    """The score rendering that can actually be produced, and whether it degraded.

    `human` asks for a band, and a band needs a scale. A dense search on
    a model kennis has never measured has none, so the request degrades
    to the raw numbers - the same choice the search mode makes, and for
    the same reason: refusing would be unhelpful and substituting
    silently would have the reader trusting a measurement that was never
    made.

    **The saying-so is the caller's**, which is why the second value
    exists. A command line prints a note; a tool may phrase it as part
    of its payload or not at all, and neither should be decided here.

    **It degrades only when *no* leg can speak.** It used to ask
    whether a single chosen scale existed, so a hybrid search on an
    uncalibrated model fell back to raw numbers although its lexical
    band was perfectly good. Now the lexical band is shown and the
    meaning band is simply absent, which is more than the reader had
    and none of it invented. Concern #379.
    """
    best = best_lexical(hits)
    banded = any(relevances(hit.result, model=hit.model, best=best) for hit in hits)
    if asked != "human" or banded:
        return asked, False
    return "raw", True
