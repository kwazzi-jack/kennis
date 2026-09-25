"""`kennis search` and `kennis read`: the commands that use the index.

A sweep is the default and a named collection is a promise. The asymmetry
matters: a collection you never mentioned is simply not part of the answer,
while the one you named is what you asked for, and replying "no hits" when
the truth is "never indexed" is the failure this exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, get_args

import click

from kennis.cli import display
from kennis.cli.context import Context, existing_corpus, resolve_context
from kennis.cli.group import KennisCommand
from kennis.cli.resolve import resolve_document
from kennis.engine.context import (
    BUNDLE_DIRNAME,
    CONTEXT_COLLECTION,
    find_bundle,
    load_bundle_index,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import ContextNotFound, NothingToIndex, SearchUnavailable
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
    bundle_hit_handle,
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

# Every scope the selector accepts, in the order the report prints them.
#
# **Context first, and that is an ordering by scope rather than by quality.**
# Unit 0 removed the cross-collection ranking because there is no common
# scale to rank on; this is not that. How specific a scope is - one project
# against the whole machine - is a fact about where knowledge lives, and a
# person asking a question inside a project is asking about that project.
SCOPE_NAMES: Final[tuple[str, ...]] = (CONTEXT_COLLECTION, *COLLECTION_NAMES)

_EVERY_SCOPE: Final = "all"

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


def _scopes(
    _context: click.Context, _parameter: click.Parameter, value: str
) -> tuple[str, ...]:
    """The selector's value as the scopes to search.

    Comma-separated rather than a repeated flag. `click.Choice` cannot
    express a list, so the validation is here, and it names both the value
    it did not recognise and every value it would have - a bare "invalid
    choice" leaves the reader to find the four names somewhere else.

    Duplicates and order in the value are discarded: the report's order is
    `SCOPE_NAMES` and nothing a caller writes should change it.
    """
    asked = [part.strip() for part in value.split(",") if part.strip()]
    if not asked:
        raise click.BadParameter("name at least one scope, or 'all'")
    if _EVERY_SCOPE in asked:
        if len(asked) > 1:
            raise click.BadParameter(
                f"'{_EVERY_SCOPE}' already means every scope; "
                "drop it or name the scopes you want"
            )
        return SCOPE_NAMES
    unknown = [name for name in asked if name not in SCOPE_NAMES]
    if unknown:
        raise click.BadParameter(
            f"unknown scope {', '.join(repr(name) for name in unknown)} - "
            f"choose from {', '.join((*SCOPE_NAMES, _EVERY_SCOPE))}"
        )
    return tuple(name for name in SCOPE_NAMES if name in asked)


@dataclass(frozen=True, slots=True)
class _Skipped:
    """A scope that was not searched, and what would change that.

    The reason is carried rather than derived from the name, because one
    name has two reasons with two different commands behind them. A corpus
    collection may be unindexed or may have no corpus at all; a bundle may
    be unindexed or may not exist in this directory. Printing
    `kennis corpus index` for a machine with no corpus gives the reader a
    command that fails - which is rule 4.4's failure in its weaker form,
    a line that runs and does not do what it said.
    """

    name: str
    reason: str
    resolution: str


@click.command(name="search", cls=KennisCommand)
@click.argument("question")
@click.option(
    "--collection",
    "selected",
    metavar="SCOPES",
    default=_EVERY_SCOPE,
    show_default=True,
    callback=_scopes,
    help="Comma-separated scopes to search: "
    + ", ".join((*SCOPE_NAMES, _EVERY_SCOPE))
    + ". 'context' is this project's bundle.",
)
@click.option("-k", "--top-k", type=int, default=None, help="How many hits to show.")
@click.option(
    "--mode",
    type=click.Choice(_MODES),
    default=None,
    help="Retrieval method. Falls back to bm25 against a lexical-only "
    "index, and does not apply to context, whose index is lexical by design.",
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
    selected: tuple[str, ...],
    top_k: int | None,
    mode: str | None,
    group: str | None,
    project: str | None,
    snippet: str,
    scores: str,
) -> None:
    """Search the corpus and this project's context, and print the best
    passages.

    **`context` is a scope, not a separate command.** The question a reader
    is answering is which scopes to look in - this project, the machine, or
    both - and that is one question, so it is one option. Without
    `--collection` every scope that has an index is searched.

    A scope you name is a promise and a scope you did not is not: asking for
    `context` outside a project is an error, while a sweep that finds no
    bundle simply reports what it did search.
    """
    if group is not None and project is not None:
        raise display.CliError("--project is an alias for --group; pass one of them.")
    # The corpus is required only if a corpus scope was selected. A bundle
    # belongs to one project and a corpus is machine-global, so searching a
    # project on a machine that has never run `corpus init` is ordinary.
    named = len(selected) < len(SCOPE_NAMES)
    wants_corpus = any(name in COLLECTION_NAMES for name in selected)
    # Required only when a corpus scope was *named*. Under a sweep a missing
    # corpus is the same kind of absence as a missing index - not part of
    # the answer - which is what lets `kennis search` work inside a project
    # on a machine that has never run `corpus init`.
    context = existing_corpus() if wants_corpus and named else resolve_context()
    corpus_exists = (context.corpus_root / ".git").is_dir()
    filters = _filters(group if group is not None else project)
    wanted = top_k or context.settings.retrieval.default_top_k
    asked = mode or context.settings.retrieval.corpus_method

    # Resolved once rather than per scope: the walk is the same answer every
    # time within one command, and the report needs to know whether there
    # was a bundle at all to choose what to say about a skipped context.
    bundle = find_bundle()
    searched: list[str] = []
    skipped: list[_Skipped] = []
    # Insertion-ordered by `SCOPE_NAMES`, which is the order the report
    # prints. Fixed rather than ranked: ordering groups by their best hit
    # would put the cross-collection comparison back in through the layout.
    groups: dict[str, list[_Hit]] = {}
    for name in [scope for scope in SCOPE_NAMES if scope in selected]:
        index = _load(context, name, bundle=bundle, named=named)
        if index is None:
            unsearched = _why_skipped(
                name, context=context, corpus_exists=corpus_exists, bundle=bundle
            )
            if unsearched is not None:
                skipped.append(unsearched)
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
        # `kennis corpus index` is the fix for an unindexed corpus and does
        # nothing for a machine that has no corpus at all - it fails with
        # "no corpus found", which is a second error to read rather than an
        # answer. So the resolution is chosen from what is actually absent.
        if not corpus_exists:
            raise NothingToIndex(
                "there is nothing to search: no corpus on this machine, and "
                "no indexed context bundle in this directory",
                resolution="kennis corpus init",
            )
        raise NothingToIndex(
            "no scope has an index yet, so there is nothing to search",
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
    skipped: list[_Skipped],
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
    # Grouped by reason rather than one line per scope. On a corpus with
    # only notes indexed, a warning per collection is two thirds of the
    # output before the answer, and the reader learns the same thing from
    # one - but two scopes skipped for different reasons need different
    # commands, so the grouping is by reason and not simply by count.
    for reason, names in _by_reason(skipped).items():
        display.note(f"not searched, {reason[0]}: {', '.join(names)}")
        display.next_step(reason[1])

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
    _read_hint(everything)


def _read_hint(hits: list[_Hit]) -> None:
    """The one command the report ends with, or nothing.

    Once for the report, not per group and not per hit. Rule 4.4 - it runs
    as printed - and the coordinates it needs are on every hit line above.
    The first hit rather than the best one, because there is no "best"
    across groups to name.

    **The first hit `kennis read` can resolve**, which is not always the
    first hit printed. `read` takes a corpus handle and a bundle document is
    addressed by path, so a hint built from a context hit would print a
    command that fails - and context is printed first. A context-only report
    therefore ends with no command at all, which is right: each hit's handle
    line is already the path, and opening a file in your own project is not
    something kennis has a verb for.
    """
    readable = next((hit for hit in hits if hit.collection != CONTEXT_COLLECTION), None)
    if readable is None:
        return
    chunk = readable.result.chunk
    display.info()
    display.next_step(
        f"kennis read {chunk.document_id} --chunks {_around(chunk.chunk_index)}",
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
    """The line under a hit: how well it matched, and how to reach it."""
    handle = (
        bundle_hit_handle(found.result, bundle_name=BUNDLE_DIRNAME)
        if found.collection == CONTEXT_COLLECTION
        else hit_handle(found.result)
    )
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
    if name != CONTEXT_COLLECTION:
        display.note(
            f"the {name} index has no dense leg, so this ran as a lexical search"
        )
    # Said for a corpus collection and not for a bundle. For a collection it
    # is news - the index was built without a backend, or part-way through a
    # model change, and the reader may not expect it. A bundle index is
    # lexical by design (section 13: a dense one would turn `context init`
    # into a model download), so reporting it as a downgrade describes a
    # degradation that did not happen. The group's own basis line already
    # says the band is relative.
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
    type=click.Choice((*COLLECTION_NAMES, CONTEXT_COLLECTION)),
    help="Look only here. All three corpus collections by default.",
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
    if collection == CONTEXT_COLLECTION:
        # Accepted by the option and refused here, rather than left to
        # click's "invalid choice: context". That message is accurate and
        # says nothing about why, and why is a decision rather than an
        # oversight: a bundle file is a file in the reader's own project, so
        # kennis has no verb for opening it. Search prints its path.
        raise display.CliError(
            "there is no read for a context file - a search hit's `path=` is "
            "the file itself, in this project, so open it with your own tools."
        )
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


def _why_skipped(
    name: str, *, context: Context, corpus_exists: bool, bundle: Path | None
) -> _Skipped | None:
    """Why this scope was not searched, or None when it is not worth saying.

    Two kinds of absence, and only one of them is news.

    **A store that exists and has not been indexed is reported**, because
    the reader has one and may well believe it was searched - which is the
    failure this whole check exists to prevent.

    **A store that does not exist, or holds nothing, is not.** Most searches
    are run outside any project, so warning that there is no bundle here
    would put a line about a feature the reader is not using above every
    answer; a machine with no corpus is told so by the refusal when nothing
    at all could be searched; and an empty collection is skipped by
    `kennis corpus index` itself, so naming that command would leave the
    same warning on the next search. Nobody believes a store they have never
    filled was searched.
    """
    if name == CONTEXT_COLLECTION:
        if bundle is None:
            return None
        return _Skipped(name, "no index yet", "kennis context index")
    if not corpus_exists:
        return None
    if not Collection(root=context.corpus_root, name=name).contents().documents:
        # An empty collection is the same kind of absence one directory
        # down. `kennis corpus index` skips a collection with no documents,
        # so naming it here would print a command that runs, changes
        # nothing, and leaves the same warning on the next search.
        return None
    return _Skipped(name, "no index yet", "kennis corpus index")


def _by_reason(skipped: list[_Skipped]) -> dict[tuple[str, str], list[str]]:
    """The skipped scopes grouped by the reason and command they share.

    Insertion-ordered, so the reasons appear in scope order and the report
    does not reshuffle itself as the corpus changes.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for scope in skipped:
        grouped.setdefault((scope.reason, scope.resolution), []).append(scope.name)
    return grouped


def _load(
    context: Context, name: str, *, bundle: Path | None, named: bool
) -> LoadedIndex | None:
    """One scope's index, or None when there is none and that is allowed.

    A missing index is fatal for a scope the user named and ordinary for one
    they did not. Anything else - an unreadable index, a binding that cannot
    be parsed - propagates either way, because silently dropping a scope the
    user believes was searched is the same failure as answering "no hits"
    for one that was never built.

    For context there are two ways to have nothing: no bundle governs this
    directory at all, and a bundle that has never been indexed. Both are
    absences of the same kind here, and they carry different resolutions,
    which is why each raises its own error rather than a shared one.
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
