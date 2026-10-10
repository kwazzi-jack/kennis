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
from typing import Final
from urllib.parse import quote, urlencode

import yaml

from kennis.context import Context
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.context.notes import bundle_documents
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, DocumentFacts
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.errors import DocumentNotFound
from kennis.engine.events import Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.resolve import ACTING
from kennis.engine.pack.store import PackInstall
from kennis.gui import words
from kennis.gui.history import Search
from kennis.gui.repairs import Repair, repairs_for
from kennis.gui.snippet import Passage, passage_of, terms_of
from kennis.gui.stream import MARKERS, SYNC_MARKERS
from kennis.holdings import Holding, document_marks
from kennis.operations import IndexBuild
from kennis.render.hits import (
    LEG_LABELS,
    LEGS,
    Hit,
    Leg,
    Relevance,
    ScoreStyle,
    best_lexical,
    relevance_phrase,
    relevances,
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
from kennis.retrieval import Sweep

# Bands rather than raw fused scores, as the other two front ends use:
# a fused score is a function of rank and says nothing an ordered list
# does not already say.
_STYLE: ScoreStyle = "human"


# The five levels from the strongest down, as the bar counts them: a
# hit at "very high" fills all five cells and one at "very low" fills
# one. A cell count is how the level reads without colour, which is
# what lets the colour be a third cue rather than the only one (#421).
_STEPS: dict[Relevance, int] = {
    "very high": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "very low": 1,
}


@dataclass(frozen=True, slots=True)
class ShownMeasure:
    """One leg's band on one hit, in the pieces a bar is drawn from.

    `label` is `render/hits.py::LEG_LABELS`'s word, so the tooltip on
    the icon is the word the command line prints. `step` is the number
    of filled cells and the strength colour they wear.
    """

    leg: Leg
    label: str
    icon: str
    level: Relevance
    step: int


@dataclass(frozen=True, slots=True)
class ShownHit:
    """One hit, in the pieces a page arranges.

    `title` and `handle` come from `render/hits.py::rendered_hit`, and
    each measure is a band that function also printed into `detail`,
    so what is read here is what `kennis search` prints and what an
    agent is handed - arranged, not reworded. There is no rank: in a
    fused list it is a position and not a measurement, and the list's
    own order already shows position (#342, #406).
    """

    title: str
    measures: tuple[ShownMeasure, ...]
    handle: str
    # **HTML, unlike the words.** The chunk rendered for this medium,
    # because leaving `##` and `[[35](https://...)]` on the page is
    # what the terminal's rule yields in a browser. Concerns #336 and
    # #297. Three parts, so one element can show the window closed and
    # the whole chunk opened without repeating any text (#415).
    passage: Passage
    collection: str
    document_id: str
    # The whole link, not its parts. A corpus hit and a bundle hit are
    # read by different routes over different stores, and a template
    # that chose between them with an `{% if %}` would be a template
    # deciding where a document lives.
    href: str

    @property
    def opens(self) -> bool:
        """Whether the passage holds more than its window."""
        return bool(self.passage.before or self.passage.after)


def shown_measures(
    measures: Sequence[tuple[Leg, Relevance]],
) -> tuple[ShownMeasure, ...]:
    return tuple(
        ShownMeasure(
            leg=leg,
            label=LEG_LABELS[leg],
            icon=words.MEASURE_ICONS[leg],
            level=level,
            step=_STEPS[level],
        )
        for leg, level in measures
    )


def shown_hits(hits: list[Hit], *, question: str = "") -> list[ShownHit]:
    """Every hit, rendered once, in rank order."""
    if not hits:
        return []
    terms = terms_of(question)
    style, _ = score_style_for(hits, _STYLE)
    best = best_lexical(hits)
    shown: list[ShownHit] = []
    for rank, hit in enumerate(hits, start=1):
        rendered = rendered_hit(hit, rank=rank, style=style, best=best, snippet="none")
        shown.append(
            ShownHit(
                title=rendered.title,
                measures=shown_measures(rendered.measures),
                # The handle is the last field of `detail` in every
                # style, which is the line `kennis read` takes.
                handle=rendered.detail_parts[-1],
                # From the chunk rather than from `rendered.body`:
                # `snippet_of` collapses the whitespace before
                # truncating, so by then the heading and the
                # paragraph after it are one line and a markdown
                # parse would make a heading of both.
                passage=passage_of(hit.result.chunk.text, terms=terms),
                collection=hit.collection,
                document_id=hit.result.chunk.document_id,
                href=_href(
                    hit.collection,
                    hit.result.chunk.document_id,
                    hit.result.chunk.chunk_index,
                    question,
                ),
            )
        )
    return shown


@dataclass(frozen=True, slots=True)
class ShownGroup:
    """One collection's answer.

    A group per collection and never one merged list, which is the
    same rule the command line follows for the same reason: there is
    no common quality scale between collections indexed differently,
    so any single ordering is a policy presented as a measurement.

    No scale line of its own any more: the key at the head of the
    results says what each measure is measured against, once (#408).
    """

    collection: str
    heading: str
    hits: list[ShownHit]


@dataclass(frozen=True, slots=True)
class ShownSkip:
    """A scope that was not searched, and the command that fixes it."""

    names: str
    resolution: str


def shown_groups_of(found: Sweep, question: str, order: str = "") -> list[ShownGroup]:
    """A sweep, in the pieces a page arranges."""
    return [
        ShownGroup(
            collection=name,
            heading=name.capitalize(),
            hits=shown_hits(ordered_by(hits, order), question=question),
        )
        for name, hits in found.groups.items()
    ]


def ordered_by(hits: Sequence[Hit], order: str) -> list[Hit]:
    """One collection's hits by one leg's own rank, or as returned.

    **Within the hits returned, which is the limit.** The fused rank
    chose them, so ordering by meaning reorders the three a combined
    search found; the best meaning-only hit may not be among them, and
    the mode control is what searches by one leg (#406). A hit the leg
    did not find goes last, keeping the fused order among those. Never
    across collections, which have no common scale (#342).
    """
    if order not in ("lexical", "meaning"):
        return list(hits)

    def leg_rank(hit: Hit) -> int | None:
        result = hit.result
        return result.bm25_rank if order == "lexical" else result.dense_rank

    def by_rank(placed: tuple[int, Hit]) -> tuple[bool, int, int]:
        position, hit = placed
        rank = leg_rank(hit)
        return (rank is None, 0 if rank is None else rank, position)

    return [hit for _, hit in sorted(enumerate(hits), key=by_rank)]


@dataclass(frozen=True, slots=True)
class ShownOrder:
    """One way to order the results, as a link to the same search."""

    label: str
    href: str
    current: bool


def shown_orders(
    *, question: str, scope: str, mode: str, order: str
) -> list[ShownOrder]:
    """The orders on offer, each a link carrying the search it reorders.

    Links rather than a select, so it works without a script: each is
    the search's own address with `order` added.
    """
    shown: list[ShownOrder] = []
    for value, label in words.ORDER_CHOICES:
        query = f"/?q={quote(question)}&scope={quote(scope)}"
        if mode:
            query += f"&mode={quote(mode)}"
        if value:
            query += f"&order={value}"
        shown.append(ShownOrder(label=label, href=query, current=value == order))
    return shown


def shown_skips(found: Sweep) -> list[ShownSkip]:
    """The scopes a sweep did not reach, one row each.

    One per scope rather than grouped by command, which is where the
    page and the command line differ deliberately: a margin can only
    carry one line, and a list has a row to spare. The words are
    `render/`'s either way.
    """
    return [
        ShownSkip(names=entry.name, resolution=entry.resolution)
        for entry in found.skipped
    ]


@dataclass(frozen=True, slots=True)
class ShownKeyLine:
    """One measure as the key explains it: its icon and its scale."""

    icon: str
    label: str
    scale: str


@dataclass(frozen=True, slots=True)
class ShownKey:
    """What the bars on this page are measured against, said once.

    **Relevance is never shown without its scale**, and it was said per
    group, which repeated one sentence above every collection (#408,
    agreed 2026-10-09: the scale is shown once and systematically). One
    line per measure that some hit on the page carries, because a key
    explaining a measure the page does not show is a sentence to skip.
    """

    lines: tuple[ShownKeyLine, ...]
    # The embedding models the meaning bands were measured for, since a
    # cosine's cuts belong to one model (`render/hits.py::_COSINE_CUTS`).
    models: tuple[str, ...]


def shown_key(found: Sweep) -> ShownKey | None:
    """The key for every band on the page, or nothing when none is shown."""
    present: set[Leg] = set()
    models: set[str] = set()
    for hits in found.groups.values():
        style, _ = score_style_for(hits, _STYLE)
        if style != "human":
            continue
        best = best_lexical(hits)
        for hit in hits:
            for leg, _ in relevances(hit.result, model=hit.model, best=best):
                present.add(leg)
                if leg == "meaning" and hit.model is not None:
                    models.add(hit.model)
    if not present:
        return None
    return ShownKey(
        lines=tuple(
            ShownKeyLine(
                icon=words.MEASURE_ICONS[leg],
                label=LEG_LABELS[leg],
                scale=relevance_phrase({leg}),
            )
            for leg in LEGS
            if leg in present
        ),
        models=tuple(sorted(models)),
    )


def _href(
    collection: str, document_id: str, chunk_index: int, question: str = ""
) -> str:
    """Where a hit leads, and it is not one route for all four scopes.

    A bundle document is not in the corpus, so `/document/context/...`
    resolved to "unknown collection" and answered a quarter of all
    searches with a 404. Concern #332.

    The chunk rides in the query string *and* in the fragment: the
    query string is what the server marks by, and the fragment is
    what the browser scrolls to. Neither alone is enough - a fragment
    never reaches the server, and a query string moves nothing.
    """
    # The query rides along so the document can offer a way back to
    # the results. Back works now that the search is in the address,
    # but a reader three hits deep should not have to press it three
    # times.
    asked = f"&q={quote(question)}" if question else ""
    tail = f"?chunk={chunk_index}{asked}#chunk-{chunk_index}"
    if collection == CONTEXT_COLLECTION:
        return f"/bundle/{quote(document_id)}{tail}"
    return f"/document/{quote(collection)}/{quote(document_id)}{tail}"


@dataclass(frozen=True, slots=True)
class ShownRecent:
    """One past search, ready to be offered again.

    `href` is composed here for the same reason `ShownHit`'s is: the
    address that re-runs a search is a fact about the routes, and a
    `{% if %}` in a template choosing one is a template deciding
    where a search lives.
    """

    query: str
    scope: str
    detail: str
    href: str


def shown_recents(searches: Sequence[Search]) -> list[ShownRecent]:
    """The past searches, each as a link that runs it again.

    The address reconstructs a search from `q`, `scope` and `mode`,
    which is what v0.6d bought and v0.7b extended - so offering one
    again is a link and not a stored result.
    """
    return [
        ShownRecent(
            query=search.query,
            scope=search.scope,
            detail=words.describe_recent(
                search.scope, search.hits, capped=search.capped, mode=search.mode
            ),
            # The mode only when there was one. An address carrying
            # `mode=` says the reader chose the default, which is a
            # different claim from not having chosen.
            href=(
                f"/?q={quote(search.query)}&scope={quote(search.scope)}"
                + (f"&mode={quote(search.mode)}" if search.mode else "")
            ),
        )
        for search in searches
    ]


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
            document.body,
            load_remote_images=load_remote_images,
            marked=marked,
            # The page already shows the title above the provenance.
            # 44 of 45 crawled pages then repeated it as their first
            # heading, so the reader saw it twice with the metadata
            # wedged between. Concern #353.
            without_title=document.frontmatter.title,
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
        body_html=to_html(
            body,
            load_remote_images=load_remote_images,
            marked=marked,
            without_title=str(title),
        ),
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
    "PALETTE_ROLES",
    "STATE_ORDER",
    "STATE_ROLES",
    "ShownBranch",
    "ShownDocument",
    "ShownEntry",
    "ShownGroup",
    "ShownHit",
    "ShownKey",
    "ShownKeyLine",
    "ShownMark",
    "ShownMeasure",
    "ShownOrder",
    "ShownOutcome",
    "ShownPaletteEntry",
    "ShownRecent",
    "ShownRow",
    "ShownSkip",
    "ShownTree",
    "ShownTreeEntry",
    "add_here_address",
    "ordered_by",
    "palette_entries",
    "shown_bundle_document",
    "shown_document",
    "shown_groups",
    "shown_groups_of",
    "shown_hits",
    "shown_key",
    "shown_measures",
    "shown_orders",
    "shown_rows",
    "shown_skips",
    "shown_tree",
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
        grouped.setdefault(
            _group_of(corpus_root, collection, _anchor(document)), []
        ).append(ShownEntry(title=document.frontmatter.title, document_id=document.id))
    ordered = sorted(grouped.items(), key=lambda pair: (pair[0] != "", pair[0]))
    return ordered, len(contents.unreadable)


def _sort_key(document: Document) -> str:
    return document.frontmatter.title.casefold()


def _anchor(document: Document | DocumentFacts) -> Path:
    """What names a document on disk: its wrapper, or its file.

    The wrapper for a wrapped document, because its own directory *is*
    the document rather than a group - the same rule the index loader
    follows, and the spelling `document_of` gives a flagged path.
    """
    return document.wrapper_dir or document.md_path


def _group_of(corpus_root: Path, collection: str, anchor: Path) -> str:
    """The directory below the collection that this document sits in."""
    relative = anchor.relative_to(corpus_root / collection)
    return relative.parent.as_posix() if relative.parent.name else ""


# Which tab adds to a place in each collection, and the field that names
# the place there: a docs page's directory is its project (#101).
_ADD_HERE: Final[dict[str, tuple[str, str]]] = {
    "literature": ("paper", "group"),
    "docs": ("site", "project"),
    "notes": ("file", "group"),
}


def add_here_address(collection: str, group: str) -> str:
    """The Add dialog opened on the tab that adds to `group` in `collection`.

    The File tab offers three collections, so it is told which one; the
    other two tabs each fix theirs.
    """
    kind, field = _ADD_HERE[collection]
    asked = {"kind": kind}
    if kind == "file":
        asked["collection"] = collection
    if group:
        asked[field] = group
    return "/add?" + urlencode(asked)


# A palette entry's kind wears an existing role on its icon and its kind
# word, so the list is not grey; the label stays ink.
PALETTE_ROLES: Final[dict[str, str]] = {
    "action": "command",
    "collection": "operation",
    "page": "value",
}


@dataclass(frozen=True, slots=True)
class ShownPaletteEntry:
    """One line of the palette: an existing route under another name.

    An action opens its dialog, as the bar's do; a place is navigated to.
    `match` is what the script compares typing against, lower-cased here
    so the script composes nothing.
    """

    label: str
    href: str
    kind: str
    icon: str
    role: str
    match: str

    @property
    def opens_a_dialog(self) -> bool:
        return self.kind == "action"


def palette_entries() -> list[ShownPaletteEntry]:
    """Every action and place, actions first."""
    listed: list[tuple[str, str, str, str]] = [
        *(
            (href, label, "action", icon)
            for href, label, icon in words.PALETTE_ACTIONS_BEFORE_INDEX
        ),
        *(
            (
                f"/index?collection={name}",
                words.index_collection(name),
                "action",
                "database",
            )
            for name in COLLECTION_NAMES
        ),
        *(
            (href, label, "action", icon)
            for href, label, icon in words.PALETTE_ACTIONS_AFTER_INDEX
        ),
        *(
            (f"/collection/{name}", name, "collection", words.COLLECTION_ICONS[name])
            for name in COLLECTION_NAMES
        ),
        *((href, label, "page", icon) for href, label, icon in words.PALETTE_PAGES),
    ]
    return [
        ShownPaletteEntry(
            label=label,
            href=href,
            kind=words.PALETTE_KINDS[kind],
            icon=icon,
            role=PALETTE_ROLES[kind],
            match=f"{label} {words.PALETTE_KINDS[kind]}".casefold(),
        )
        for href, label, kind, icon in listed
    ]


# A mark wears an existing role, never a new colour. Not yet indexed is
# `added` because that is what it is to the index; unreadable is an error.
STATE_ROLES: Final[dict[str, str]] = {
    "unindexed": "added",
    "changed": "changed",
    "unreadable": "error",
}

# Worst first. Search cannot see an unreadable document at all; it finds
# a changed one by text the document no longer has, which is a false
# answer; a new one it merely does not find yet, which is an incomplete
# one - the distinction `Freshness` draws between stale and behind.
STATE_ORDER: Final[tuple[str, ...]] = ("unreadable", "changed", "unindexed")


@dataclass(frozen=True, slots=True)
class ShownMark:
    """A state as the tree draws it: a letter, its role, its sentence."""

    state: str
    letter: str
    role: str
    sentence: str


def _mark(state: str, sentence: str | None = None) -> ShownMark | None:
    if not state:
        return None
    return ShownMark(
        state=state,
        letter=words.STATE_LETTERS[state],
        role=STATE_ROLES[state],
        sentence=sentence or words.STATE_WORDS[state],
    )


@dataclass(frozen=True, slots=True)
class ShownTreeEntry:
    """One document in the pane's tree.

    `document_id` is empty for an unreadable document: there is no
    identifier kennis can vouch for, so nothing to open or move, but it
    is listed so it can be found - a count beneath the tree could not be.
    """

    title: str
    document_id: str
    mark: ShownMark | None

    @property
    def state(self) -> str:
        return self.mark.state if self.mark else ""


@dataclass(frozen=True, slots=True)
class ShownBranch:
    """One group's entries, and the worst state beneath it.

    `group` is empty for the collection's own top level, which is drawn
    without a heading.
    """

    group: str
    entries: list[ShownTreeEntry]
    mark: ShownMark | None
    add_here: str

    @property
    def state(self) -> str:
        return self.mark.state if self.mark else ""


@dataclass(frozen=True, slots=True)
class ShownTree:
    """A collection's branch of the pane: its groups, and what may be done.

    `movable` is False for docs, whose directory is its project (#101).
    `groups` is what the Move field offers, named as they are held.
    """

    collection: str
    top: ShownBranch
    branches: list[ShownBranch]
    groups: list[str]
    attention: int
    movable: bool


def shown_tree(context: Context, collection: str) -> ShownTree:
    """One collection as the pane draws it, each document with its state."""
    root = context.corpus_root
    contents = Collection(root=root, name=collection).contents()
    marks = document_marks(context, collection)
    grouped: dict[str, list[ShownTreeEntry]] = {}
    for document in sorted(contents.documents, key=_sort_key):
        anchor = _anchor(document)
        grouped.setdefault(_group_of(root, collection, anchor), []).append(
            ShownTreeEntry(
                title=document.frontmatter.title,
                document_id=document.id,
                mark=_mark(marks.state_of(root, anchor)),
            )
        )
    for facts in contents.unreadable:
        anchor = _anchor(facts)
        grouped.setdefault(_group_of(root, collection, anchor), []).append(
            ShownTreeEntry(
                title=facts.title or facts.md_path.name,
                document_id="",
                mark=_mark("unreadable"),
            )
        )
    branches = [
        _branch(collection, group, entries)
        for group, entries in sorted(
            grouped.items(), key=lambda pair: (pair[0] != "", pair[0])
        )
    ]
    top = (
        branches.pop(0)
        if branches and branches[0].group == ""
        else _branch(collection, "", [])
    )
    every = [entry for branch in (top, *branches) for entry in branch.entries]
    return ShownTree(
        collection=collection,
        top=top,
        branches=branches,
        groups=[branch.group for branch in branches],
        attention=sum(1 for entry in every if entry.mark),
        movable=collection != "docs",
    )


def _branch(collection: str, group: str, entries: list[ShownTreeEntry]) -> ShownBranch:
    attention = [entry.state for entry in entries if entry.mark]
    worst = next((state for state in STATE_ORDER if state in attention), "")
    return ShownBranch(
        group=group,
        entries=entries,
        mark=_mark(worst, words.attention_count(len(attention))) if worst else None,
        add_here=add_here_address(collection, group),
    )


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
    # Whether the form that produced this should empty itself.
    # A write that happened leaves stale text behind, and pressing
    # the button again writes it twice; a write that was refused
    # leaves text the reader would otherwise have to type again.
    clears: bool = False


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
