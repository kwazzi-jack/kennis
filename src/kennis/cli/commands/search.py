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
from kennis.cli.context import Context, existing_corpus
from kennis.cli.group import KennisCommand
from kennis.cli.resolve import resolve_document
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import NothingToIndex, SearchUnavailable
from kennis.engine.rag.embedding import resolve_host
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.models import Filter, SearchResult
from kennis.engine.rag.search import (
    ChunkRange,
    Mode,
    parse_chunk_range,
    read_span,
    search,
)
from kennis.render.hits import (
    SCORE_STYLES,
    Basis,
    basis_for,
    hit_handle,
    hit_headline,
    raw_scores,
    relevance,
    relevance_phrase,
)
from kennis.render.words import (
    describe_document,
    describe_span,
    snippet_of,
)

_MODES: Final[tuple[str, ...]] = get_args(Mode.__value__)

# How many chunks either side of the anchor a passage carries. Named so
# that `--before`/`--after` can be told apart from an explicit value equal
# to the default, which is what makes refusing them possible.
_CONTEXT_DEFAULT: Final = 1


@dataclass(frozen=True, slots=True)
class _Hit:
    """One result, which collection produced it, and on what scale.

    The collection is carried alongside rather than read off the chunk,
    because a merged list is three lists interleaved and a reader has to be
    able to tell them apart without looking anything up.

    `basis` travels with the hit rather than with the list because each
    collection has its own index and so its own embedding model: a corpus
    part-way through a model change can hold one index a relevance band is
    calibrated for and one it is not. `None` is "this hit cannot be banded".
    """

    collection: str
    result: SearchResult
    basis: Basis | None
    model: str | None


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
@click.option(
    "--scores",
    type=click.Choice(SCORE_STYLES),
    default="human",
    show_default=True,
    help="How well each hit matched: a level, the raw per-leg numbers, or nothing.",
)
def search_command(
    question: str,
    collection: str | None,
    top_k: int | None,
    mode: str | None,
    group: str | None,
    project: str | None,
    snippet: str,
    scores: str,
) -> None:
    """Search the corpus and print the best-matching passages."""
    context = existing_corpus()
    if group is not None and project is not None:
        raise display.CliError("--project is an alias for --group; pass one of them.")
    filters = _filters(group if group is not None else project)
    wanted = top_k or context.settings.retrieval.default_top_k
    asked = mode or context.settings.retrieval.corpus_method

    searched: list[str] = []
    skipped: list[str] = []
    # Insertion-ordered by `COLLECTION_NAMES`, which is the order the report
    # prints. Fixed rather than ranked: ordering groups by their best hit
    # would put the cross-collection comparison back in through the layout.
    groups: dict[str, list[_Hit]] = {}
    for name in [collection] if collection else list(COLLECTION_NAMES):
        index = _load(context, name, named=collection is not None)
        if index is None:
            skipped.append(name)
            continue
        searched.append(name)
        running = _fallback(index, asked, name)
        model = index.binding.model.model if index.binding.model else None
        basis = basis_for(model, dense_ran=running != "bm25")
        found = [
            _Hit(collection=name, result=result, basis=basis, model=model)
            for result in search(
                index,
                question,
                top_k=wanted,
                filters=filters,
                mode=running,
                # The address, from the configuration in force now. It is
                # not in the stored binding, because it is not part of what
                # the vectors are. Concern #210.
                host=resolve_host(
                    index.binding.model.kind if index.binding.model else "",
                    context.settings.embedding.base_url or None,
                ),
            )
        ]
        # `top_k` per collection, not across them: each group is a complete
        # answer from its source rather than a truncated share of a blend.
        # No slice here - `search` is asked for `wanted` and returns at most
        # that, so one would be dead code. An injection proved it was.
        if found:
            groups[name] = found

    if not searched:
        raise NothingToIndex(
            "no collection has an index yet, so there is nothing to search",
            resolution="kennis corpus index",
        )

    # Not sorted across collections, and that is the point. A fused score is
    # `sum 1/(k+rank)` over the legs that ranked a chunk, so a hybrid
    # collection contributes two terms where a lexical-only one contributes
    # one and scores double for the same rank - on a real corpus every
    # dual-leg hit in the candidate window beat every single-leg hit, always.
    # Concern #229. Each group keeps its own ranking instead.
    _report(groups, searched, skipped, snippet, scores)


def _report(
    groups: dict[str, list[_Hit]],
    searched: list[str],
    skipped: list[str],
    snippet: str,
    scores: str,
) -> None:
    """One group per collection, each with its own ranking and its own scale.

    Not one merged list. There is no common quality scale between
    collections indexed differently, so every single-column ordering is a
    policy presented as a measurement - and the fused score it would sort on
    is biased by leg count besides (#229). Grouping states what kennis knows:
    it ranks within a collection, and across them it only presents.
    """
    if skipped:
        # One line for all of them. On a corpus with only notes indexed, one
        # warning per collection is two thirds of the output before the
        # answer, and the reader learns the same thing from one.
        display.note(
            f"not searched, no index yet: {', '.join(skipped)}",
        )
        display.next_step("kennis corpus index")

    if not groups:
        display.operation("Searched", ", ".join(searched))
        display.note("no matching passages")
        return

    everything = [hit for hits in groups.values() for hit in hits]
    style = _score_style(everything, scores)
    display.operation("Found", _summary(groups))
    for name, hits in groups.items():
        display.info()
        display.operation(name.capitalize(), _basis_phrase(hits, style))
        # Per group, which is what it wanted to be: the objection its old
        # docstring recorded - that a per-collection best makes every
        # collection's top hit "very high" - only bit while one column
        # served every collection. Each group now carries a line saying its
        # band is relative. Concern #231.
        best = _best_lexical(hits)
        for rank, found in enumerate(hits, start=1):
            display.hit(hit_headline(rank, found.result))
            display.hit_detail(_hit_detail(found, style, best))
            if snippet != "none":
                display.body(
                    snippet_of(found.result.chunk.text, full=snippet == "full"),
                    indent="      ",
                )
    # Once for the report, not per group and not per hit. Rule 4.4 - it runs
    # as printed - and the coordinates it needs are on every hit line above.
    # The first group's first hit, because it is the first thing printed, not
    # because it is the best: there is no "best" across groups to name.
    first = everything[0].result.chunk
    display.info()
    display.next_step(
        f"kennis read {first.document_id} --chunks {_around(first.chunk_index)}",
        note="to read one in context",
    )


def _basis_phrase(hits: list[_Hit], style: str) -> str:
    """What this group's relevance levels are a band of, or nothing.

    Empty when no level is being printed at all, so a `--scores raw` report
    does not carry a heading explaining a column it does not have.
    """
    if style != "human":
        return ""
    bases = {hit.basis for hit in hits if hit.basis is not None}
    if len(bases) != 1:
        return ""
    return relevance_phrase(bases.pop())


def _around(chunk_index: int) -> str:
    """The range that puts one chunk in context, as `--chunks` takes it.

    The arithmetic `--before` and `--after` used to do, done once here so
    that the printed command runs as printed (rule 4.4). `max(0, ...)` is
    the part that matters: a hit at chunk 0 would otherwise print `-1:2`,
    and `-1` is the document's *last* chunk - so the hint would send a
    reader to the wrong end of it.
    """
    return f"{max(0, chunk_index - 1)}:{chunk_index + 2}"


def _score_style(hits: list[_Hit], asked: str) -> str:
    """The score rendering that can actually be produced.

    `human` asks for a band, and a band needs a scale. A dense search on a
    model kennis has never measured has none, so the request degrades to the
    raw numbers and says so - the same choice `_fallback` makes about a
    search mode, and for the same reason: refusing would be unhelpful and
    substituting silently would have the reader trusting a measurement that
    was never made.
    """
    if asked != "human" or any(found.basis is not None for found in hits):
        return asked
    display.note(
        "no relevance band is calibrated for this embedding model, so these "
        "are the raw scores"
    )
    return "raw"


def _summary(groups: dict[str, list[_Hit]]) -> str:
    """`5 in docs, 2 in notes`: how much came from where.

    Which is the thing a grouped report can say and a merged one could not,
    and it is why the groups need no ranking between them - a reader sees
    the distribution before the first hit.

    The basis is not here. It belongs to a group, and this line spans them.
    """
    return ", ".join(f"{len(hits)} in {name}" for name, hits in groups.items())


def _best_lexical(hits: list[_Hit]) -> float:
    """The best BM25 score in the list, which the lexical band is a fraction of.

    Within one collection, which is the only place a BM25 score is
    comparable. It used to be taken across all of them, because one column
    served every collection and a per-collection best would have made each
    collection's top hit "very high" with nothing to say so. The group
    heading says so now. Concern #231.
    """
    return max(
        (hit.result.bm25_score for hit in hits if hit.result.bm25_score is not None),
        default=0.0,
    )


def _hit_detail(found: _Hit, style: str, best: float) -> str:
    """The line under a hit: how well it matched, and how to read it."""
    handle = hit_handle(found.result)
    if style == "none":
        return handle
    if style == "raw":
        return f"{raw_scores(found.result)}  {handle}"
    if found.basis is None:
        return handle
    level = relevance(found.result, basis=found.basis, model=found.model, best=best)
    if level is None:
        return handle
    return f"relevance: {level}  {handle}"


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
@click.argument("handle")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three by default.",
)
@click.option(
    "--chunks",
    "chunk_range",
    metavar="RANGE",
    default=None,
    help="Read these chunks instead of the whole document, python-style: "
    "'3', '0:3', '2:', ':3', '-1'. No step - a passage is contiguous.",
)
@click.option(
    "--frontmatter",
    is_flag=True,
    help="Include the document's YAML frontmatter in the output.",
)
def read_command(
    handle: str,
    collection: str | None,
    chunk_range: str | None,
    frontmatter: bool,
) -> None:
    """Print a document, or the passage around one of its chunks.

    **`HANDLE` is anything that names the document**: its identifier, its
    title, the filename it has on disk with or without the extension, a
    paper's citekey or arXiv identifier or DOI, a docs page's
    `project/page`. The same resolution `corpus remove` and `corpus move`
    use, so a handle that works for one works for all of them.

    Without `--chunks` the document is read **from the corpus**, not from
    the index, and a document that has never been indexed is still readable.
    With `--chunks` the passage is stitched out of the index, which is what a
    search hit's coordinates address - so that one, and only that one, needs
    `kennis corpus index` to have run.

    **`--chunks` is a python slice** over the document's own chunks: `3` is
    one, `0:3` is the first three, `2:` runs to the end, `-1` is the last.
    There is no step, because a passage that is not contiguous is not a
    passage. It is an option value rather than a bracket on the handle
    (`read x[0:3]`) because `[` and `]` are glob characters: the shell
    rewrites an unquoted bracket expression against whatever files are in the
    working directory, silently, and differently from one directory to the
    next. Concern #205.

    **One output contract either way: stdout is the text, stderr is the
    provenance.** `kennis read x > x.md` and `kennis read x --chunks 3 |
    less` both get the markdown and nothing else. A contract that changed
    with a flag would put a report line on the front of one of them.
    """
    context = existing_corpus()
    if chunk_range is None:
        _read_document(context, handle, collection, frontmatter=frontmatter)
        return
    if frontmatter:
        # Silently ignoring it is how a person concludes the command did not
        # work: it runs, it exits zero, and it does exactly what it would
        # have done without the flag.
        raise display.CliError(
            "--frontmatter belongs to a whole-document read; drop --chunks to use it."
        )
    _read_span(context, handle, collection, chunks=parse_chunk_range(chunk_range))


def _read_document(
    context: Context, handle: str, collection: str | None, *, frontmatter: bool
) -> None:
    """The whole document, as markdown, on stdout.

    The provenance goes to stderr rather than being dropped: the reader of a
    terminal still wants to know which document answered, and the reader of
    a pipe must not be given a report line in the middle of their file. The
    same split `config show` makes.
    """
    found, document = resolve_document(context, handle, collection)
    display.operation("Read", describe_document(found.name, document), stderr=True)
    text = (
        document.md_path.read_text(encoding="utf-8") if frontmatter else document.body
    )
    display.body(text.rstrip("\n"))


def _read_span(
    context: Context, handle: str, collection: str | None, *, chunks: ChunkRange
) -> None:
    """One range of a document's chunks, stitched out of the index.

    The handle is resolved against the corpus first, so `--chunks` accepts
    every name the whole-document read does rather than the identifier
    alone. Only then is the index asked, and only the collection the
    document was actually found in.
    """
    found, document = resolve_document(context, handle, collection)
    # Not `_load`: that one answers "an index, or None where None is
    # allowed", and here it is not allowed - the document is known to be in
    # this one collection and there is nowhere else to look. Asking for a
    # required index directly keeps the type honest instead of narrowing an
    # optional that could never be None.
    index = _index_of(context, found.name)
    try:
        span = read_span(index, document.id, chunks=chunks)
    except SearchUnavailable as error:
        # The document is in the corpus and not in the index, which is a
        # stale index rather than a missing document - so the resolution is
        # to rebuild, not to go looking for another name.
        error.add_note("run `kennis corpus index`")
        raise
    display.operation(
        "Read",
        describe_span(found.name, span, document.frontmatter.title),
        stderr=True,
    )
    display.body(span.text)


def _index_of(context: Context, name: str) -> LoadedIndex:
    """One collection's index, or the error naming the command that builds it.

    `NothingToIndex` already says which collection and carries
    `kennis corpus index` as its resolution, so nothing is added here.
    """
    return load_index(index_root(context.corpus_root), name)


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
