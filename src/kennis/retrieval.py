"""Searching one scope: where the index is, which mode it can run.

Beside `context.py` and `logs.py`, and there for the same reason
concern #292 gives: these are questions every front end asks and no
front end owns. The MCP server had them privately; the graphical
interface asks exactly the same ones and may not import the server,
so keeping them there would have made one front end the other's
library - which design section 20 says none of them is.

The command line is deliberately not moved onto this. It sweeps every
scope and reports which it skipped and why, which is a different
operation from "search this one and fail if it has no index".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast, get_args

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION, load_bundle_index
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import (
    ContextNotFound,
    KennisError,
    NothingToIndex,
    SettingsError,
)
from kennis.engine.rag.embedding import resolve_host
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.models import Filter
from kennis.engine.rag.search import Mode, search
from kennis.render.hits import Hit

# The most a caller may ask for. A ceiling rather than a validation
# error: a caller asking for 500 wants "lots", and refusing them is
# less useful than giving them the most that is sensible.
MAX_TOP_K = 20

# The four scopes a search may cover, in the order a report lists
# them. Fixed rather than ranked: ordering groups by their best hit
# would state a comparison across collections that kennis cannot
# make. `context` leads because a bundle is the nearest knowledge.
SCOPE_NAMES: Final[tuple[str, ...]] = (CONTEXT_COLLECTION, *COLLECTION_NAMES)

# What the reader types, or picks, to mean all four.
EVERY_SCOPE: Final = "all"


def context_for(collection: str) -> Context:
    """The context a search of `collection` runs in.

    The bundle scope resolves a project and the others require a
    corpus, which is the one thing that differs between them.
    """
    return resolve_context() if collection == CONTEXT_COLLECTION else existing_corpus()


def search_scope(collection: str, question: str, top_k: int = 5) -> list[Hit]:
    """The best hits for `question` in exactly one scope.

    Raises `ContextNotFound` outside a project when the scope is the
    bundle, and `NothingToIndex` when the scope has no index. **A
    named scope with no index is an error here**, where the command
    line's sweep skips it: a caller asking about one scope and told
    "no hits" for an index that was never built has been told
    something false.
    """
    context = context_for(collection)
    index = index_for(context, collection)
    model = index.binding.model.model if index.binding.model else None
    running = mode_for(context, index, collection)
    results = search(
        index,
        question,
        top_k=max(1, min(top_k, MAX_TOP_K)),
        filters=None,
        mode=running,
        host=resolve_host(
            index.binding.model.kind if index.binding.model else "",
            context.settings.embedding.base_url or None,
        ),
    )
    return [
        Hit(collection=collection, result=result, model=model) for result in results
    ]


def index_for(context: Context, collection: str) -> LoadedIndex:
    if collection == CONTEXT_COLLECTION:
        bundle = find_bundle()
        if bundle is None:
            raise ContextNotFound
        return load_bundle_index(bundle)
    return load_index(index_root(context.corpus_root), collection)


def mode_for(context: Context, index: LoadedIndex, collection: str) -> Mode:
    """The mode this index can actually run.

    A bundle has its own setting, because a dense bundle index costs
    what `retrieval.context_method` exists to avoid. Either way an
    index with no vectors runs lexically rather than failing: a fresh
    install may have no embedding backend at all.
    """
    asked = (
        context.settings.retrieval.context_method
        if collection == CONTEXT_COLLECTION
        else context.settings.retrieval.corpus_method
    )
    if index.matrix is None:
        return "bm25"
    return "bm25" if asked == "bm25" else "dense" if asked == "dense" else "hybrid"


def chunk_range(
    context: Context, collection: str, document_id: str, chunk_index: int
) -> tuple[int, int] | None:
    """Where one chunk of one document starts and ends, in characters.

    `Chunk` records `char_start` and `char_end` when the index is
    built, so this is a lookup and not a computation - which is why
    a reader can mark a passage exactly without re-chunking anything.

    `None` rather than an exception for every way of not finding it:
    an absent index, an unindexed document and a chunk number typed
    into a query string are three different situations with one
    answer for the caller, which is to show the document unmarked.
    The reader must not lose the page over the mark.

    Here rather than in a front end because it is the same question
    #292's other two were: every front end that shows a document
    beside a search result will ask it, and none of them owns it.
    """
    if chunk_index < 0:
        return None
    try:
        index = index_for(context, collection)
    except KennisError:
        return None
    for chunk in index.chunks:
        if chunk.document_id == document_id and chunk.chunk_index == chunk_index:
            return (chunk.char_start, chunk.char_end)
    return None


@dataclass(frozen=True, slots=True)
class Skipped:
    """A scope that was not searched, and the command that changes that.

    **No sentence.** The words are `render/`'s, because a value that
    already carries the facts as fields must not also carry a
    sentence built from them: the command line groups two skips onto
    one line and a page lists them, and neither could if the phrase
    arrived pre-made. Concern #81.

    The resolution is carried rather than derived from the name,
    because one name has two commands behind it. A corpus collection
    with no index wants `kennis corpus index --collection <name>`; a
    bundle wants `kennis context index`. Printing the corpus command
    for a machine with no corpus hands the reader a line that runs
    and does nothing - rule 4.4's failure in its weaker form.
    """

    name: str
    resolution: str


@dataclass(frozen=True, slots=True)
class Sweep:
    """What searching several scopes at once came to.

    `groups` is keyed in `SCOPE_NAMES` order and **never sorted by
    best hit**. Ranking collections against each other would put the
    cross-collection comparison back in through the layout, and it is
    the comparison the labelled bands exist to prevent: an absolute
    cosine and a position relative to this query's best lexical hit
    are different measurements, and each collection's lexical band is
    relative to its own best.

    `degraded` names the scopes that ran lexically although more was
    asked of them. Carried rather than printed, because `retrieval`
    may not import a front end - which is the whole reason the sweep
    could not simply be moved as it stood.
    """

    groups: dict[str, list[Hit]]
    searched: tuple[str, ...]
    skipped: tuple[Skipped, ...]
    degraded: tuple[str, ...]


def sweep(
    question: str,
    *,
    scopes: Sequence[str],
    named: bool,
    top_k: int | None = None,
    filters: list[Filter] | None = None,
    mode: str | None = None,
) -> Sweep:
    """Search every scope in `scopes` that can be searched.

    `named` is the difference between a scope the reader asked for
    and one swept into, and it cannot be inferred from the count: a
    missing index is fatal for the first and ordinary for the second.
    Answering a reader who asked for `docs` with hits from elsewhere
    answers a different question than the one they put.

    Raises when nothing at all could be searched, rather than
    returning an empty sweep. "No passages matched" for a corpus that
    was never indexed tells the reader their corpus is empty, which
    is a different and wrong conclusion.

    Moved here from the command line, which held it privately while
    `mode_for` stated the same mode rule beside it. Concern #314.
    """
    wants_corpus = any(scope != CONTEXT_COLLECTION for scope in scopes)
    # Required only when a corpus scope was *named*. Under a sweep a
    # missing corpus is the same kind of absence as a missing index,
    # which is what lets a search work inside a project on a machine
    # that has never run `corpus init`.
    context = existing_corpus() if wants_corpus and named else resolve_context()
    corpus_exists = (context.corpus_root / ".git").is_dir()
    wanted = top_k or context.settings.retrieval.default_top_k
    # Resolved once rather than per scope: the walk gives the same
    # answer every time within one search, and the caller needs to
    # know whether there was a bundle at all to say anything sensible
    # about a skipped context.
    bundle = find_bundle()

    searched: list[str] = []
    skipped: list[Skipped] = []
    degraded: list[str] = []
    groups: dict[str, list[Hit]] = {}

    for name in [scope for scope in SCOPE_NAMES if scope in scopes]:
        index = _load(context, name, bundle=bundle, named=named)
        if index is None:
            unsearched = _why_skipped(
                name, context=context, corpus_exists=corpus_exists, bundle=bundle
            )
            if unsearched is not None:
                skipped.append(unsearched)
            continue
        searched.append(name)
        # Per scope, not once for the sweep. A bundle's method is its
        # own setting with its own default, because a dense bundle
        # index costs what `retrieval.context_method` exists to avoid.
        # An explicit mode overrides both.
        asked = mode or (
            context.settings.retrieval.context_method
            if name == CONTEXT_COLLECTION
            else context.settings.retrieval.corpus_method
        )
        running = _runnable(index, asked)
        if running != asked and asked != "bm25":
            degraded.append(name)
        model = index.binding.model.model if index.binding.model else None
        found = [
            Hit(collection=name, result=result, model=model)
            for result in search(
                index,
                question,
                top_k=wanted,
                filters=filters,
                mode=running,
                # The address, from the configuration in force now. It
                # is not in the stored binding, because it is not part
                # of what the vectors are. Concern #210.
                host=resolve_host(
                    index.binding.model.kind if index.binding.model else "",
                    context.settings.embedding.base_url or None,
                ),
            )
        ]
        # `top_k` per collection, not across them: each group is a
        # complete answer from its source rather than a truncated
        # share of a blend.
        if found:
            groups[name] = found

    if not searched:
        raise nothing_to_search(skipped, corpus_exists=corpus_exists)
    return Sweep(
        groups=groups,
        searched=tuple(searched),
        skipped=tuple(skipped),
        degraded=tuple(degraded),
    )


def _runnable(index: LoadedIndex, asked: str) -> Mode:
    """The mode this index can actually run.

    Refusing would be wrong: a fresh install may have no embedding
    backend at all, and requiring `--mode bm25` on every search is a
    flag people alias away. A silent downgrade would be worse - it
    would have them comparing result quality against a dense index
    they do not have, which is why the caller is told through
    `Sweep.degraded`.
    """
    if index.matrix is not None or asked == "bm25":
        return as_mode(asked)
    return "bm25"


# `Mode` is a PEP 695 alias, and **`get_args(Mode)` returns `()`** for
# one - the members are behind `__value__`. Read wrongly, the check
# below rejects every mode there is and names none of them in the
# refusal, which is how this arrived. Concern #339.
_MODES: Final[tuple[str, ...]] = get_args(Mode.__value__)


def as_mode(asked: str) -> Mode:
    """`asked` as the engine's own type.

    A cast in effect, and narrow on purpose: the command line builds
    its `Choice` from the same members, so the only way here with
    anything else is a settings file, which pydantic has already
    validated against the same three values.
    """
    if asked not in _MODES:
        raise SettingsError(
            f"'{asked}' is not a search mode; use one of {', '.join(_MODES)}",
            resolution="kennis config get retrieval.corpus_method",
        )
    return cast(Mode, asked)


def _load(
    context: Context, name: str, *, bundle: Path | None, named: bool
) -> LoadedIndex | None:
    """One scope's index, or None when there is none and that is allowed.

    A missing index is fatal for a scope the user named and ordinary
    for one they did not. Anything else - an unreadable index, a
    binding that cannot be parsed - propagates either way, because
    silently dropping a scope the user believes was searched is the
    same failure as answering "no hits" for one that was never built.

    For context there are two ways to have nothing: no bundle governs
    this directory at all, and a bundle that has never been indexed.
    Both are absences of the same kind here, and they carry different
    resolutions, which is why each raises its own error.
    """
    try:
        if name == CONTEXT_COLLECTION:
            if bundle is None:
                raise ContextNotFound
            return load_bundle_index(bundle)
        return load_index(index_root(context.corpus_root), name)
    except (NothingToIndex, ContextNotFound):
        if named:
            raise
        return None


def _why_skipped(
    name: str, *, context: Context, corpus_exists: bool, bundle: Path | None
) -> Skipped | None:
    """Why this scope was not searched, or None when it is not worth saying.

    Two kinds of absence, and only one of them is news.

    **A store that exists and has not been indexed is reported**,
    because the reader has one and may well believe it was searched -
    which is the failure this whole check exists to prevent.

    **A store that does not exist, or holds nothing, is not.** Most
    searches run outside any project, so warning that there is no
    bundle here would put a line about a feature the reader is not
    using above every answer; a machine with no corpus is told so by
    the refusal when nothing at all could be searched; and an empty
    collection is skipped by `kennis corpus index` itself, so naming
    that command would leave the same warning on the next search.
    Nobody believes a store they have never filled was searched.
    """
    if name == CONTEXT_COLLECTION:
        if bundle is None:
            return None
        return Skipped(name, "kennis context index")
    if not corpus_exists:
        return None
    if not Collection(root=context.corpus_root, name=name).contents().documents:
        return None
    return Skipped(name, f"kennis corpus index --collection {name}")


def nothing_to_search(
    skipped: Sequence[Skipped], *, corpus_exists: bool
) -> NothingToIndex:
    """The refusal when no scope could be searched, naming a real command.

    **The first skipped scope's own command**, and `skipped` is in
    `SCOPE_NAMES` order, so a project with an unindexed bundle is told
    `kennis context index` rather than something about the corpus.
    That is the ordinary state of a fresh clone - the bundle's index
    is gitignored (#248), so the documents arrive and the index does
    not - which makes it the first thing many readers will ever see.

    An empty `skipped` means nothing exists to index: every scope was
    dropped for not being there at all, which `_why_skipped` reports
    as None. Then the command is the one that creates something.
    """
    if skipped:
        return NothingToIndex(
            "nothing that could be searched has an index yet",
            resolution=skipped[0].resolution,
        )
    if not corpus_exists:
        # `kennis corpus index` would fail with "no corpus found",
        # which is a second error to read rather than an answer.
        return NothingToIndex(
            "there is nothing to search: no corpus on this machine, and no "
            "context bundle in this directory",
            resolution="kennis corpus init",
        )
    return NothingToIndex(
        "there is nothing to search: the corpus is empty",
        resolution="kennis corpus add --help",
    )


__all__ = [
    "EVERY_SCOPE",
    "MAX_TOP_K",
    "SCOPE_NAMES",
    "Skipped",
    "Sweep",
    "as_mode",
    "chunk_range",
    "context_for",
    "index_for",
    "mode_for",
    "nothing_to_search",
    "search_scope",
    "sweep",
]
