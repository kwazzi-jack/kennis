"""Turning engine values into what a template places.

The interface's half of `render/`. It calls the shared renderers -
`render/hits.py` for a hit, `render/html.py` for a document - and
arranges what comes back into values a template can lay out without
deciding anything itself.

**A template does no formatting.** Everything a person reads is
composed here or in `render/`, so that a change of layout cannot
change a word and a change of wording cannot need a template edit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

import yaml

from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.context.notes import bundle_documents
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.errors import DocumentNotFound
from kennis.engine.events import Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.resolve import ACTING
from kennis.engine.pack.store import PackInstall
from kennis.gui import words
from kennis.gui.repairs import Repair, repairs_for
from kennis.gui.stream import MARKERS, SYNC_MARKERS
from kennis.holdings import Holding
from kennis.operations import IndexBuild
from kennis.render.hits import (
    Hit,
    ScoreStyle,
    best_lexical,
    rendered_hit,
    score_style_for,
)
from kennis.render.html import MarkedRange, to_html
from kennis.render.packs import (
    describe_action,
    describe_corpus_claim_needed,
    describe_declarations,
    describe_deferred,
    describe_install,
    describe_sync,
    describe_unfetched,
)
from kennis.render.refusals import describe_refusal, remedies_for_refusal
from kennis.render.words import describe_busy_indexes, describe_uncommitted_build

# Bands rather than raw fused scores, as the other two front ends use:
# a fused score is a function of rank and says nothing an ordered list
# does not already say.
_STYLE: ScoreStyle = "human"


@dataclass(frozen=True, slots=True)
class ShownHit:
    """One hit, in the pieces a page arranges.

    The three text fields come from `render/hits.py::rendered_hit`, so
    what is read here is what `kennis search` prints and what an agent
    is handed. The two extra fields are coordinates, not words: a page
    needs them to build a link, and a link is not something `render/`
    should be composing.
    """

    headline: str
    detail: str
    body: str | None
    collection: str
    document_id: str
    # The whole link, not its parts. A corpus hit and a bundle hit are
    # read by different routes over different stores, and a template
    # that chose between them with an `{% if %}` would be a template
    # deciding where a document lives.
    href: str


def shown_hits(hits: list[Hit]) -> list[ShownHit]:
    """Every hit, rendered once, in rank order."""
    if not hits:
        return []
    style, _ = score_style_for(hits, _STYLE)
    best = best_lexical(hits)
    shown: list[ShownHit] = []
    for rank, hit in enumerate(hits, start=1):
        rendered = rendered_hit(hit, rank=rank, style=style, best=best, snippet="short")
        shown.append(
            ShownHit(
                headline=rendered.headline,
                detail=rendered.detail,
                body=rendered.body,
                collection=hit.collection,
                document_id=hit.result.chunk.document_id,
                href=_href(
                    hit.collection,
                    hit.result.chunk.document_id,
                    hit.result.chunk.chunk_index,
                ),
            )
        )
    return shown


def _href(collection: str, document_id: str, chunk_index: int) -> str:
    """Where a hit leads, and it is not one route for all four scopes.

    A bundle document is not in the corpus, so `/document/context/...`
    resolved to "unknown collection" and answered a quarter of all
    searches with a 404. Concern #332.

    The chunk rides in the query string *and* in the fragment: the
    query string is what the server marks by, and the fragment is
    what the browser scrolls to. Neither alone is enough - a fragment
    never reaches the server, and a query string moves nothing.
    """
    tail = f"?chunk={chunk_index}#chunk-{chunk_index}"
    if collection == CONTEXT_COLLECTION:
        return f"/bundle/{quote(document_id)}{tail}"
    return f"/document/{quote(collection)}/{quote(document_id)}{tail}"


@dataclass(frozen=True, slots=True)
class ShownDocument:
    """One document, ready to place."""

    title: str
    document_id: str
    collection: str
    path: str
    body_html: str
    # True when the body referred to an image that was not fetched, so
    # a page can offer to load them. Offered only when there is
    # something to load, because a control that does nothing is worse
    # than no control.
    has_blocked_images: bool


def shown_document(
    corpus_root: Path,
    collection: str,
    document_id: str,
    *,
    load_remote_images: bool,
    marked: MarkedRange | None = None,
) -> ShownDocument:
    """Read one document and render it.

    Raises `DocumentNotFound` or `DocumentInvalid`, which the interface
    turns into a page rather than a traceback.

    `marked` is a character range of the body, already decided
    elsewhere: this function reads the corpus and never the index, so
    whether a chunk exists and whether its offsets can be trusted are
    both settled before the call. Keeping the index out of here is
    what lets a document be read when its collection has none.
    """
    held = Collection(root=corpus_root, name=collection)
    document = held.resolve(document_id)
    return ShownDocument(
        title=document.frontmatter.title,
        document_id=document.id,
        collection=collection,
        path=relative_to_corpus(document.md_path, corpus_root),
        body_html=to_html(
            document.body, load_remote_images=load_remote_images, marked=marked
        ),
        has_blocked_images=_refers_remotely(document.body),
    )


def shown_bundle_document(
    bundle: Path,
    relative_path: str,
    *,
    load_remote_images: bool,
    marked: MarkedRange | None = None,
) -> ShownDocument:
    """One note out of this project's bundle, rendered.

    **The path is checked by membership, not by normalisation.** It
    arrives from the address bar, and the bundle sits inside the
    user's own repository, so a traversal would serve whatever the
    process can read to whatever reached the port. Comparing against
    the documents the bundle actually holds has no encoding to be
    fooled by, where `resolve()` and a prefix test have several.

    The body is split from the frontmatter the same way the bundle
    loader splits it, because the index recorded its offsets against
    that body: rendering the whole file would put every chunk's
    offsets out by the length of the header.
    """
    held = {
        path.relative_to(bundle).as_posix(): path for path in bundle_documents(bundle)
    }
    path = held.get(relative_path)
    if path is None:
        raise DocumentNotFound(
            f"'{relative_path}' is not in this project's bundle",
            resolution="kennis context status",
        )
    text = path.read_text(encoding="utf-8")
    try:
        frontmatter, body = split_frontmatter(text)
    except yaml.YAMLError:
        # The loader is lenient here for the same reason: a bundle
        # file's identity is its path, so an unreadable header costs
        # its metadata and not the text the user wanted found.
        frontmatter, body = {}, text
    title = frontmatter.get("title") or path.stem
    return ShownDocument(
        title=str(title),
        document_id=relative_path,
        collection=CONTEXT_COLLECTION,
        path=f"{bundle.name}/{relative_path}",
        body_html=to_html(body, load_remote_images=load_remote_images, marked=marked),
        has_blocked_images=_refers_remotely(body),
    )


def _refers_remotely(markdown: str) -> bool:
    """Whether the body refers to an image kennis would have to fetch.

    Crude on purpose - a substring, not a parse. Being wrong here
    offers a control that loads nothing, or withholds one the reader
    could have used; neither justifies parsing the document twice.
    """
    return "](http://" in markdown or "](https://" in markdown


__all__ = [
    "ShownDocument",
    "ShownEntry",
    "ShownHit",
    "ShownOutcome",
    "ShownRow",
    "shown_bundle_document",
    "shown_document",
    "shown_groups",
    "shown_hits",
    "shown_rows",
]


@dataclass(frozen=True, slots=True)
class ShownRow:
    """One collection, as a table row."""

    collection: str
    count: str
    index: str
    is_current: bool


@dataclass(frozen=True, slots=True)
class ShownEntry:
    """One document in a listing: what to show and what to link to."""

    title: str
    document_id: str


def shown_rows(held: Sequence[Holding]) -> list[ShownRow]:
    """Every collection, phrased for a table."""
    return [
        ShownRow(
            collection=holding.collection,
            count=words.describe_count(holding),
            index=words.describe_holding(holding),
            is_current=holding.is_current,
        )
        for holding in held
    ]


def shown_groups(
    corpus_root: Path, collection: str
) -> tuple[list[tuple[str, list[ShownEntry]]], int]:
    """A collection's documents by group, and how many could not be read.

    Grouped by the directory a document sits in, which is what the
    corpus layout means by a group - `corpus tree` shows the same
    shape. The ungrouped ones come first under an empty name, because
    a collection with no groups should not lead with a heading.
    """
    contents = Collection(root=corpus_root, name=collection).contents()
    grouped: dict[str, list[ShownEntry]] = {}
    for document in sorted(contents.documents, key=_sort_key):
        grouped.setdefault(_group_of(corpus_root, collection, document), []).append(
            ShownEntry(title=document.frontmatter.title, document_id=document.id)
        )
    ordered = sorted(grouped.items(), key=lambda pair: (pair[0] != "", pair[0]))
    return ordered, len(contents.unreadable)


def _sort_key(document: Document) -> str:
    return document.frontmatter.title.casefold()


def _group_of(corpus_root: Path, collection: str, document: Document) -> str:
    """The directory below the collection that this document sits in.

    The wrapper is the anchor for a wrapped document, because its own
    directory *is* the document rather than a group - the same rule
    the index loader follows.
    """
    anchor = document.wrapper_dir or document.md_path
    relative = anchor.relative_to(corpus_root / collection)
    return relative.parent.as_posix() if relative.parent.name else ""


@dataclass(frozen=True, slots=True)
class ShownOutcome:
    """What became of a write, in the pieces a page arranges.

    `role` is a semantic role name from `render/theme.py`, so the
    template applies a class and decides nothing: whether a repeated
    note is good news or a warning is a judgement, and judgements do
    not belong in markup.
    """

    message: str
    role: str
    where: str | None = None
    resolution: str | None = None


@dataclass(frozen=True, slots=True)
class ShownItem:
    """One item an operation touched, and why where there is a why.

    `repairs` is empty except on a refusal the interface can actually
    act on. An offer that cannot work is worse than none, so a paper
    whose text sits behind a publisher gets the sentence alone.
    """

    marker: str
    name: str
    outcome: str
    detail: str | None = None
    remedies: tuple[str, ...] = ()
    repairs: tuple[Repair, ...] = ()


@dataclass(frozen=True, slots=True)
class ShownJob:
    """What a finished operation amounts to, in the pieces a page lays out.

    One shape for four operations. They differ in what `headline` says
    and in which items they produce, and not in how a reader reads
    them - a list of things that happened under a line saying how many.
    """

    headline: str
    items: tuple[ShownItem, ...] = ()
    notes: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    role: str = "role-added"


def shown_add(report: AddReport) -> ShownJob:
    """An add, with a repair beneath every refusal that has one."""
    items = tuple(_shown_outcome(outcome) for outcome in report.outcomes)
    added = report.counts.get(Outcome.ADDED, 0)
    return ShownJob(
        headline=words.added_headline(added, report),
        items=items,
        # A sentence rather than `kennis corpus index`, because the
        # control that would run it is on this same page. Printing the
        # command beside its own button asks the reader to leave the
        # interface to do what the interface does.
        notes=(words.NOT_SEARCHABLE_YET,) if added else (),
        role="role-added" if added else "role-muted",
    )


def _shown_outcome(outcome: AddOutcome) -> ShownItem:
    """One item of an add, with its way out where it has one.

    **A form or a command, never both.** `remedies_for_refusal` returns
    a command for exactly the refusals `repairs_for` can build a form
    from, so showing both puts a terminal command beside a button that
    does the same thing - which asks the reader to leave the interface
    to do what the interface does. The command is what is left for a
    refusal this interface cannot act on, and there it is all there is.
    """
    shown = ShownItem(
        marker=MARKERS[outcome.outcome],
        name=outcome.title or outcome.identifier,
        outcome=outcome.outcome.value,
    )
    if outcome.outcome is not Outcome.FAILED or outcome.refusal is None:
        return shown
    repairs = repairs_for(outcome.refusal)
    return replace(
        shown,
        detail=describe_refusal(outcome.refusal),
        repairs=repairs,
        remedies=() if repairs else remedies_for_refusal(outcome.refusal),
    )


def shown_index(built: IndexBuild) -> ShownJob:
    """An index build, one line per collection that had anything in it."""
    notes: list[str] = []
    if built.busy:
        # Before the emptiness note and instead of it: a build that
        # reached no collection built nothing, and "there is nothing
        # to index" at a corpus that is full is false rather than
        # merely unhelpful. Concern #331.
        notes.append(describe_busy_indexes(built.busy))
    elif not built.built:
        notes.append(words.NOTHING_TO_INDEX)
    if not built.committed:
        notes.append(describe_uncommitted_build())
    return ShownJob(
        headline=words.indexed_headline(built),
        items=tuple(
            ShownItem(
                marker="+",
                name=index.collection,
                outcome="added",
                detail=words.describe_built(index),
            )
            for index in built.built
        ),
        notes=tuple(notes),
        role="role-added" if built.built else "role-muted",
    )


def shown_corpus_sync(result: CorpusSync) -> ShownJob:
    """A corpus sync, with the two things it deliberately did not do."""
    notes: list[str] = []
    steps: list[str] = []
    if result.edited:
        notes.append(describe_corpus_claim_needed(len(result.edited)))
        steps.extend(f"kennis corpus claim {held}" for held in result.edited)
    if result.failed:
        notes.append(describe_unfetched(result.failed))
    if result.deferred:
        notes.append(describe_deferred(result.deferred))
    acted = any(action.verdict in ACTING for action in result.actions)
    if acted:
        notes.append(words.NOT_SEARCHABLE_YET)
    return ShownJob(
        headline=describe_sync(result.counts, noun="document"),
        role="role-added" if acted else "role-muted",
        items=tuple(
            ShownItem(
                marker=SYNC_MARKERS.get(action.verdict, ">"),
                name=action.address,
                outcome=action.verdict,
                detail=describe_action(action),
            )
            for action in result.actions
        ),
        notes=tuple(notes),
        next_steps=tuple(steps),
    )


def shown_bundle_sync(result: BundleSync) -> ShownJob:
    """A context sync. No commit happened and the page has to say so."""
    notes: list[str] = [words.BUNDLE_NOT_COMMITTED]
    if result.deferred:
        notes.append(describe_deferred(result.deferred))
    acted = any(action.verdict in ACTING for action in result.actions)
    return ShownJob(
        headline=describe_sync(result.counts),
        role="role-added" if acted else "role-muted",
        items=tuple(
            ShownItem(
                marker=SYNC_MARKERS.get(action.verdict, ">"),
                name=action.address,
                outcome=action.verdict,
                detail=describe_action(action),
            )
            for action in result.actions
        ),
        notes=tuple(notes),
        # `kennis context index` stays a command, unlike the corpus
        # one: this interface has no control that indexes a bundle, so
        # the terminal really is where that is done.
        next_steps=("kennis context index",) if acted else (),
    )


def shown_install(install: PackInstall) -> ShownJob:
    """A pack install, and the fact that nothing is searchable yet.

    Said because "Installed" otherwise implies the content is in the
    corpus, and it is not: this records what the provider declared and
    a sync materialises it.
    """
    declared = describe_declarations(install)
    return ShownJob(
        headline=f"{install.outcome} {install.pack_id}",
        items=(
            ShownItem(
                marker="+",
                name=install.pack_id,
                outcome=install.outcome,
                detail=describe_install(install),
            ),
        ),
        notes=((declared,) if declared else ()) + (words.NOTHING_MATERIALISED,),
        next_steps=("kennis corpus sync", "kennis context sync"),
    )
