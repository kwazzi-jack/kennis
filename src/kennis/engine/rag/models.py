"""The search-facing data models.

Deliberately source-agnostic. A `Document` or `Chunk` carries a small set of
typed provenance fields plus a free-form `metadata` mapping for whatever the
loader wants to attach - citekey, title and year for a paper, project and
page for a documentation page, anything at all for a loader that does not
exist yet. Nothing here knows what frontmatter is.

These are pydantic models rather than the frozen dataclasses the rest of the
engine uses for in-process values, and the reason is narrow: a `Chunk`
round-trips through the index on disk, so it needs validating on the way back
in. The others follow it for consistency within this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from kennis.engine._glob import globstar_regex

# Whatever a loader attached. Heterogeneous by design - this is the seam that
# keeps retrieval from knowing about collections - so the values are `Any`
# and a filter is what interprets them.
type Metadata = dict[str, Any]

type ChunkPredicate = Callable[[Chunk], bool]

FilterOp = Literal["eq", "in", "contains", "gte", "lte", "glob"]


class Document(BaseModel):
    """One source document, as a loader yields it, before chunking."""

    id: str
    text: str
    # Surfaced to the user as "where found".
    source_path: str
    # Where relative assets resolve from - a document's own directory, when
    # it has one. None for a document that has no assets beside it.
    base_path: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class Chunk(BaseModel):
    """A retrievable span of text, with provenance back to its document."""

    # `f"{document_id}::{chunk_index}"`, which is unique only because the
    # index is rebuilt wholesale. Incremental chunk-level update would break
    # this quietly.
    id: str
    collection: str
    document_id: str
    chunk_index: int
    text: str

    source_path: str
    char_start: int
    char_end: int
    # The nearest preceding heading, or None for text before the first one.
    section: str | None = None

    metadata: Metadata = Field(default_factory=dict)


class SearchResult(BaseModel):
    """A ranked chunk, with enough provenance to explain its rank.

    `score` is the fused value used for ordering and is comparable only
    across hits of the same query - never across collections or queries. The
    per-leg values are kept beside it because "why is this first" is a
    question a maintainer asks and a fused score alone cannot answer. Each
    is None when that leg did not run.

    A *rank* and a *score* are absent for different reasons, which is why
    they are not set together. `dense_rank` is a position inside the leg's
    candidate window and is None for a hit the window did not reach.
    `dense_score` is a cosine, defined for every chunk against every query,
    so it is present for every hit of a search whose dense leg ran - even
    one fused in by the lexical leg alone. A relevance band reads the score,
    and would otherwise have nothing to say about a hit it could measure.
    """

    chunk: Chunk
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    dense_score: float | None = None


class Filter(BaseModel):
    """A predicate over a chunk's metadata.

    `field` may be a dotted path as well as a plain key, because kennis
    frontmatter namespaces its per-collection fields into a block: the year
    of a paper is `bib.year` and never `year`, so a filter that could only
    name top-level keys could not reach anything collection-specific.

    `contains` matches a case-insensitive substring; `gte` and `lte` compare
    numerically when both sides parse as numbers and lexically otherwise, so
    a year stored as a string still orders as a number; `glob` matches a
    shell-style pattern with `**` spanning separators.
    """

    field: str
    op: FilterOp
    value: Any

    def predicate(self) -> ChunkPredicate:
        field, op, value = self.field, self.op, self.value

        def check(chunk: Chunk) -> bool:
            actual = _lookup(chunk.metadata, field)
            # A missing field is false rather than an error: a filter runs
            # over a mixed collection where not every chunk has every field.
            if actual is None:
                return False
            if op == "eq":
                return bool(actual == value)
            if op == "in":
                return actual in value
            if op == "contains":
                return str(value).lower() in str(actual).lower()
            if op == "glob":
                return _glob_match(str(actual), str(value))
            return (
                _orders_before(value, actual)
                if op == "gte"
                else _orders_before(actual, value)
            )

        return check


def combine_filters(filters: list[Filter] | None) -> ChunkPredicate | None:
    """Every filter, joined with and. None means there is no filtering to do.

    None rather than a predicate that always passes, so the caller can skip
    the walk entirely instead of running a function over every chunk to learn
    that it passes.
    """
    if not filters:
        return None
    predicates = [one.predicate() for one in filters]
    return lambda chunk: all(predicate(chunk) for predicate in predicates)


def _lookup(metadata: Metadata, dotted_field: str) -> object:
    """Follow a dotted field name into nested metadata, e.g. `bib.year`.

    A plain name with no dots still resolves as one top-level lookup. The
    result is `object` rather than `Any` so that every use of it has to
    narrow first: metadata is heterogeneous by design, and a value read out
    of it is not known to be anything until it is checked.
    """
    current: object = metadata
    for segment in dotted_field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
        if current is None:
            return None
    return current


def _glob_match(actual: str, pattern: str) -> bool:
    """Shell-style match of a group path, which also selects its descendants.

    Two rules, both chosen because they are what the pattern looks like it
    should do. `*` and `?` stop at a separator and `**` spans them, so
    `quartical/*` is one level and `**/gains` is any depth; plain `fnmatch`
    cannot express this, since its `*` crosses `/`. And a pattern matching a
    group also selects everything filed under it, because selecting a group
    and not its contents would be useless for filtering.
    """
    regex = globstar_regex(pattern.rstrip("/"))
    if regex.fullmatch(actual):
        return True
    segments = actual.split("/")
    return any(
        regex.fullmatch("/".join(segments[:depth])) for depth in range(1, len(segments))
    )


def _orders_before(smaller: object, larger: object) -> bool:
    """Whether `smaller <= larger`, numerically when both sides are numbers.

    A year lives in frontmatter as a string, and comparing those as text
    would put '999' after '2011'. Falling back to text rather than refusing
    keeps a filter usable over a field that is not a number at all.
    """
    numbers = _as_numbers(smaller, larger)
    if numbers is not None:
        return numbers[0] <= numbers[1]
    return str(smaller) <= str(larger)


def _as_numbers(left: object, right: object) -> tuple[float, float] | None:
    """Both sides as floats, or None when either is not a number.

    Converted through `str` so that this works for whatever came out of YAML
    - an int, a float, or the string a year is usually written as.
    """
    try:
        return float(str(left)), float(str(right))
    except ValueError:
        return None
