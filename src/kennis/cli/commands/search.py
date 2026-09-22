"""`kennis search` and `kennis read`: the commands that use the index.

A sweep is the default and a named collection is a promise. The asymmetry
matters: a collection you never mentioned is simply not part of the answer,
while the one you named is what you asked for, and replying "no hits" when
the truth is "never indexed" is the failure this exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, get_args

import click

from kennis.cli import display
from kennis.cli.context import Context, resolve_context
from kennis.cli.group import KennisCommand
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import CorpusNotFound, NothingToIndex, SearchUnavailable
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.models import Filter, SearchResult
from kennis.engine.rag.search import Mode, read_span, search
from kennis.render.words import count_of, describe_hit, describe_span, snippet_of

_MODES: Final[tuple[str, ...]] = get_args(Mode.__value__)


@dataclass(frozen=True, slots=True)
class _Hit:
    """One result, and which collection produced it.

    Carried alongside rather than read off the chunk, because a merged list
    is three lists interleaved and a reader has to be able to tell them apart
    without looking anything up.
    """

    collection: str
    result: SearchResult


@click.command(name="search", cls=KennisCommand)
@click.argument("question")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Search only this one. Every indexed collection by default.",
)
@click.option("-k", "--top-k", type=int, default=None, help="How many hits to show.")
@click.option(
    "--mode",
    type=click.Choice(_MODES),
    default=None,
    help="Retrieval method. Falls back to bm25 against a lexical-only index.",
)
@click.option(
    "--group",
    metavar="PATTERN",
    help="Restrict to documents filed under a group, shell-style: 'botany', "
    "'physics/*'. Quote it - your shell expands an unquoted '*' first.",
)
@click.option(
    "--project",
    help="Docs only: an alias for --group, since a page's project is its group.",
)
@click.option(
    "--snippet",
    type=click.Choice(["none", "short", "full"]),
    default="short",
    show_default=True,
    help="How much of each hit's text to show.",
)
def search_command(
    question: str,
    collection: str | None,
    top_k: int | None,
    mode: str | None,
    group: str | None,
    project: str | None,
    snippet: str,
) -> None:
    """Search the corpus and print the best-matching passages."""
    context = _existing_corpus()
    if group is not None and project is not None:
        raise display.CliError("--project is an alias for --group; pass one of them.")
    filters = _filters(group if group is not None else project)
    wanted = top_k or context.settings.retrieval.default_top_k
    asked = mode or context.settings.retrieval.corpus_method

    searched: list[str] = []
    skipped: list[str] = []
    hits: list[_Hit] = []
    for name in [collection] if collection else list(COLLECTION_NAMES):
        index = _load(context, name, named=collection is not None)
        if index is None:
            skipped.append(name)
            continue
        searched.append(name)
        running = _fallback(index, asked, name)
        hits += [
            _Hit(collection=name, result=result)
            for result in search(
                index, question, top_k=wanted, filters=filters, mode=running
            )
        ]

    if not searched:
        raise NothingToIndex(
            "no collection has an index yet, so there is nothing to search",
            resolution="kennis corpus index",
        )

    # Ordered by the fused score across collections. Defensible precisely
    # because reciprocal rank fusion is a function of rank: 1/(k+rank) means
    # the same thing in literature as in notes, where a BM25 score would not.
    hits.sort(key=lambda hit: hit.result.score, reverse=True)
    _report(hits[:wanted], searched, skipped, snippet)


def _report(
    hits: list[_Hit], searched: list[str], skipped: list[str], snippet: str
) -> None:
    if skipped:
        # One line for all of them. On a corpus with only notes indexed, one
        # warning per collection is two thirds of the output before the
        # answer, and the reader learns the same thing from one.
        display.note(
            f"not searched, no index yet: {', '.join(skipped)}",
        )
        display.next_step("kennis corpus index")

    if not hits:
        display.operation("Searched", ", ".join(searched))
        display.note("no matching passages")
        return

    display.operation("Found", count_of(len(hits), "passage"))
    for hit in hits:
        display.detail("=", describe_hit(hit.collection, hit.result))
        if snippet != "none":
            display.plain(snippet_of(hit.result.chunk.text, full=snippet == "full"))


def _fallback(index: LoadedIndex, asked: str, name: str) -> Mode:
    """The mode this index can actually run, saying so when it is not the one
    asked for.

    Refusing would be wrong: a fresh install may have no embedding backend at
    all, and requiring `--mode bm25` on every search is a flag people alias
    away. A silent downgrade would be worse - it would have them comparing
    result quality against a dense index they do not have.
    """
    if index.matrix is not None or asked == "bm25":
        return _as_mode(asked)
    display.note(f"the {name} index has no dense leg, so this ran as a lexical search")
    return "bm25"


def _as_mode(asked: str) -> Mode:
    """`asked` as the engine's own type.

    A cast in effect, and narrow on purpose: click's `Choice` is built from
    `Mode`'s own members, so the only way here with anything else is a
    settings file, which pydantic has already validated against the same
    three values.
    """
    if asked not in _MODES:
        raise display.CliError(f"unknown search mode '{asked}'")
    return "bm25" if asked == "bm25" else "dense" if asked == "dense" else "hybrid"


def _filters(group: str | None) -> list[Filter] | None:
    """The metadata predicates a search runs with.

    `glob` rather than `eq`, so `physics/*` reaches a subgroup. The loader
    records `group` on every chunk, which is why this needs no knowledge of
    how the corpus is laid out.
    """
    if group is None:
        return None
    return [Filter(field="group", op="glob", value=group)]


@click.command(name="read", cls=KennisCommand)
@click.argument("document_id")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. Every indexed collection by default.",
)
@click.option("--chunk", type=int, default=0, show_default=True, help="Anchor chunk.")
@click.option("--before", type=int, default=1, show_default=True)
@click.option("--after", type=int, default=1, show_default=True)
def read_command(
    document_id: str, collection: str | None, chunk: int, before: int, after: int
) -> None:
    """Show the passage around one chunk of a document.

    The companion to a hit rather than a second `cat`: a search returns one
    chunk and a reader wants what surrounds it, which is why this reads the
    index and not the file.
    """
    context = _existing_corpus()

    looked = False
    for name in [collection] if collection else list(COLLECTION_NAMES):
        index = _load(context, name, named=collection is not None)
        if index is None:
            continue
        looked = True
        try:
            span = read_span(
                index, document_id, chunk_index=chunk, before=before, after=after
            )
        except SearchUnavailable:
            # Not in this collection's index. In a sweep that is ordinary -
            # a document lives in one collection - so the search continues
            # and only the last one answers.
            continue
        display.operation("Read", describe_span(name, span))
        display.plain(span.text)
        return

    if not looked:
        raise NothingToIndex(
            "no collection has an index yet, so there is nothing to read",
            resolution="kennis corpus index",
        )
    raise SearchUnavailable(
        f"'{document_id}' is not in any index",
        resolution="kennis corpus index",
    )


def _load(context: Context, name: str, *, named: bool) -> LoadedIndex | None:
    """One collection's index, or None when there is none and that is allowed.

    A missing index is fatal for the collection the user named and ordinary
    for one they did not. Anything else - an unreadable index, a binding that
    cannot be parsed - propagates either way, because silently dropping a
    collection the user believes was searched is the same failure as
    answering "no hits" for one that was never built.
    """
    try:
        return load_index(index_root(context.corpus_root), name)
    except NothingToIndex:
        if named:
            raise
        return None


def _existing_corpus() -> Context:
    context = resolve_context()
    if not (context.corpus_root / ".git").is_dir():
        raise CorpusNotFound(
            f"there is no kennis corpus at {context.corpus_root}",
            resolution="kennis corpus init",
        )
    return context
