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

import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from urllib.parse import quote, urlencode

import yaml

from kennis.context import Context
from kennis.engine.backup import BackupReport
from kennis.engine.context.index import (
    project_group,
    project_of_group,
)
from kennis.engine.context.notes import bundle_documents
from kennis.engine.context.packs import pack_files, pack_group, pack_of_group
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOutcome, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.copying import COPY_ORIGIN_SCHEME
from kennis.engine.corpus.document import Document, DocumentFacts
from kennis.engine.corpus.ids import derive_id, natural_key_for_docs
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.schema import (
    COLLECTION_NAMES,
    DocsFrontmatter,
    DocumentFrontmatter,
    LiteratureFrontmatter,
)
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.docs.versions import (
    ProjectVersions,
    excluded_versions,
    project_versions,
    versions_holding,
)
from kennis.engine.errors import DocumentNotFound, KennisError, PackNotInstalled
from kennis.engine.events import Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.installed import list_installed
from kennis.engine.pack.resolve import ACTING
from kennis.engine.pack.store import PackInstall
from kennis.engine.rag.models import Chunk
from kennis.gui import words
from kennis.gui.history import Search
from kennis.gui.repairs import Repair, WayOut, repairs_for, ways_out_for
from kennis.gui.stream import MARKERS, SYNC_MARKERS
from kennis.holdings import (
    DocumentMarks,
    DocumentState,
    Holding,
    contents_of,
    document_marks,
)
from kennis.operations import IndexBuild
from kennis.render.backup import describe_written
from kennis.render.hits import (
    LEG_LABELS,
    LEGS,
    Hit,
    Leg,
    Relevance,
    ScoreStyle,
    best_lexical,
    docs_versions_of,
    relevance_phrase,
    relevances,
    rendered_hit,
    score_style_for,
)
from kennis.render.html import (
    Heading,
    MarkedRange,
    PassageHtml,
    headings_of,
    passage_html,
    query_pattern,
    terms_of,
    to_html,
)
from kennis.render.packs import (
    describe_bundle_sync,
    describe_declarations,
    describe_declared,
    describe_deferred,
    describe_install,
    describe_kept_copies,
    describe_kept_copy,
    describe_made_yours,
    describe_no_declaration,
    describe_not_installed,
    describe_outcome_of,
    describe_sync,
    describe_unfetched,
    describe_why_unfetched,
)
from kennis.render.refusals import refusal_fact, remedies_for_refusal
from kennis.render.words import (
    describe_busy_indexes,
    group_name,
)
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

    `title` (the document's; the section heads the passage) and `handle`
    come from `render/hits.py::rendered_hit`, and
    each measure is a band that function also printed into `detail`,
    so what is read here is what `kennis search` prints and what an
    agent is handed - arranged, not reworded. There is no rank: in a
    fused list it is a position and not a measurement, and the list's
    own order already shows position (#342, #406).
    """

    title: str
    measures: tuple[ShownMeasure, ...]
    handle: str
    # **HTML, unlike the words.** The chunk rendered once, by the
    # document's renderer, parted where the reader's words first occur:
    # a closed passage shows the second part faded, an opened one both
    # (#454). Concerns #336 and #297.
    passage: PassageHtml
    collection: str
    document_id: str
    # The whole link, not its parts. A corpus hit and a bundle hit are
    # read by different routes over different stores, and a template
    # that chose between them with an `{% if %}` would be a template
    # deciding where a document lives.
    href: str
    # `pydantic 2.14`, or the versions a merged passage stands for; empty
    # for a hit that is not a versioned docs page (#489).
    version: str = ""

    @property
    def opens(self) -> bool:
        """Whether the passage is too long or too tall to show whole. A
        passage that fits is drawn whole, its lead included."""
        return not self.passage.fits


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


# About the characters of prose a closed passage shows before its fade:
# six lines at the reading measure. More, and the passage opens.
_PASSAGE_FITS: Final = 360


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
                title=rendered.document_title,
                measures=shown_measures(rendered.measures),
                # The handle is the last field of `detail` in every
                # style, which is the line `kennis read` takes.
                handle=rendered.detail_parts[-1],
                # From the chunk rather than from `rendered.body`:
                # `snippet_of` collapses the whitespace before
                # truncating, so by then the heading and the
                # paragraph after it are one line and a markdown
                # parse would make a heading of both.
                passage=passage_html(
                    hit.result.chunk.text,
                    terms=terms,
                    fits=_PASSAGE_FITS,
                    section=rendered.section,
                    title=rendered.document_title,
                ),
                collection=hit.collection,
                document_id=hit.result.chunk.document_id,
                href=_href(
                    hit.collection,
                    hit.result.chunk.document_id,
                    hit.result.chunk.chunk_index,
                    question,
                ),
                version=docs_versions_of(hit) or "",
            )
        )
    return shown


def versions_query(versions: Sequence[str]) -> str:
    """`&version=...` for each docs version a search was asked for, so a
    link that runs it again searches the same versions (#489)."""
    return "".join(f"&version={quote(version)}" for version in versions)


@dataclass(frozen=True, slots=True)
class ShownVersionChoice:
    """One version of one project, as a checkbox beside the search box."""

    value: str
    version: str
    checked: bool
    current: bool


@dataclass(frozen=True, slots=True)
class ShownVersionProject:
    project: str
    choices: tuple[ShownVersionChoice, ...]


def shown_version_choices(
    held: Mapping[str, ProjectVersions], chosen: Sequence[str]
) -> list[ShownVersionProject]:
    """Each project that holds more than one version, its versions ticked
    as `chosen` searches them; none when there is nothing to choose.

    Ticked by `excluded_versions`, the rule the search itself follows,
    so the boxes cannot say something other than what was searched. A
    choice that cannot be read ticks the default, and the page says why
    above the results.
    """
    try:
        left_out = set(excluded_versions(held, chosen))
    except KennisError:
        left_out = set(excluded_versions(held, ()))
    return [
        ShownVersionProject(
            project=project,
            choices=tuple(
                ShownVersionChoice(
                    value=f"{project}={version}",
                    version=version,
                    checked=f"{project}/{version}" not in left_out,
                    current=version == versions.current,
                )
                for version in versions.held
            ),
        )
        for project, versions in held.items()
        if len(versions.held) > 1
    ]


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
    name: str
    icon: str
    hits: list[ShownHit]

    @property
    def count(self) -> int:
        """How many hits this collection gave, which is all of them shown."""
        return len(self.hits)


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
            name=group_name(name),
            # The bundle is drawn as a folder in the pane, so here too.
            icon=words.COLLECTION_ICONS.get(name, "folder"),
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
    *,
    question: str,
    scope: str,
    mode: str,
    order: str,
    versions: Sequence[str] = (),
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
        query += versions_query(versions)
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
    project = project_of_group(collection)
    if project is not None:
        # In the query, because a project's name may hold a `/` (#512).
        return (
            f"/bundle/{quote(document_id)}?project={quote(project)}"
            f"&chunk={chunk_index}{asked}#chunk-{chunk_index}"
        )
    pack = pack_of_group(collection)
    if pack is not None:
        return f"/pack/{quote(pack)}/{quote(document_id)}{tail}"
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
                + versions_query(search.versions)
                + (f"&project={quote(search.project)}" if search.project else "")
            ),
        )
        for search in searches
    ]


@dataclass(frozen=True, slots=True)
class ShownDetail:
    """One row of the inspector's details.

    `verbatim` is for a value that must be read or typed exactly - an
    identifier, a path - and is drawn in the monospace face.
    """

    label: str
    value: str
    verbatim: bool = False
    # Where the value leads, when it is an address anyone can follow: an
    # arXiv id, a DOI, a bibcode, the page a document was fetched from.
    href: str = ""
    # Offered to the clipboard: the citekey, which is typed into a paper.
    copyable: bool = False
    # False for a page of this window - the original a copy was made from -
    # which opens here rather than in a tab that cannot reach back.
    external: bool = True


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
    # The directory below the collection, for the breadcrumbs; empty at
    # the top, and always empty in the bundle, whose folders are paths.
    group: str = ""
    # What the last breadcrumb calls the document: its citekey when it
    # has one, because that is what a paper is cited by.
    handle: str = ""
    byline: str | None = None
    details: tuple[ShownDetail, ...] = ()
    outline: tuple[Heading, ...] = ()
    # The same docs page in the other versions held, as (version, link):
    # what changed between two releases is a click away (#489).
    other_versions: tuple[tuple[str, str], ...] = ()
    # The breadcrumb for the store it is in, when that is not a corpus
    # collection: a bundle has no page of its own, so its crumb is words
    # with no link, and a pack's leads to the packs (14g).
    crumb_name: str = ""
    crumb_href: str = ""

    @property
    def crumb(self) -> tuple[str, str]:
        """The breadcrumb's words and where it leads; no link when empty."""
        if self.crumb_name:
            return self.crumb_name, self.crumb_href
        return self.collection, f"/collection/{self.collection}"


def byline_of(frontmatter: DocumentFrontmatter) -> str | None:
    """Who wrote it and when, or what it documents, under the title."""
    if isinstance(frontmatter, LiteratureFrontmatter):
        parts = [
            part for part in (frontmatter.bib.authors, frontmatter.bib.year) if part
        ]
        return ", ".join(parts) or None
    if isinstance(frontmatter, DocsFrontmatter):
        docs = frontmatter.docs
        return f"{docs.project} {docs.version}" if docs.version else docs.project
    return None


def document_details(
    frontmatter: DocumentFrontmatter,
    *,
    collection: str,
    group: str,
    state: DocumentState | None,
    original: tuple[str, str] | None = None,
) -> tuple[ShownDetail, ...]:
    """What the frontmatter says, as the inspector's rows.

    Only what this document has. `state` is None when the index cannot
    be checked, and then the row is left out, as the tree draws no mark:
    "kennis cannot check" is not "searchable".
    """
    label = words.DETAIL_LABELS
    rows = [ShownDetail(label["collection"], collection)]
    if group:
        rows.append(ShownDetail(label["group"], group))
    rows.append(ShownDetail(label["id"], frontmatter.id, verbatim=True))
    if isinstance(frontmatter, LiteratureFrontmatter):
        bib = frontmatter.bib
        rows.append(
            ShownDetail(label["citekey"], bib.citekey, verbatim=True, copyable=True)
        )
        for key, value in (
            ("arxiv", bib.arxiv_id),
            ("doi", bib.doi),
            ("bibcode", bib.bibcode),
        ):
            if value:
                rows.append(
                    ShownDetail(
                        label[key],
                        value,
                        verbatim=True,
                        href=_RESOLVERS[key].format(quote(value, safe="/:.()")),
                    )
                )
    if isinstance(frontmatter, DocsFrontmatter):
        rows.append(ShownDetail(label["project"], frontmatter.docs.project))
        rows.append(ShownDetail(label["page"], frontmatter.docs.page, verbatim=True))
        if frontmatter.docs.version:
            rows.append(ShownDetail(label["version"], frontmatter.docs.version))
        # What the site calls its own release, when it says something the
        # folder does not: `latest` built as 2.2.0rc1.
        release = frontmatter.docs.release
        if release and release != frontmatter.docs.version:
            rows.append(ShownDetail(label["release"], release))
    source = frontmatter.source
    if original is not None:
        # A copy's source is a document here, not a conversion (#514).
        identifier, href = original
        rows.append(
            ShownDetail(
                label["copied"], identifier, verbatim=True, href=href, external=False
            )
        )
    else:
        fetched = source.origin.removeprefix("url:")
        rows.append(
            ShownDetail(
                label["source"],
                source.origin,
                verbatim=True,
                href=fetched if fetched.startswith(("https://", "http://")) else "",
            )
        )
        rows.append(ShownDetail(label["converted"], source.via))
    rows.append(ShownDetail(label["added"], source.at.date().isoformat()))
    if state is not None:
        rows.append(ShownDetail(label["index"], words.INDEX_STATES[state]))
    return tuple(rows)


# Where an identifier is looked up by anyone, not by kennis.
_RESOLVERS: Final[dict[str, str]] = {
    "arxiv": "https://arxiv.org/abs/{}",
    "doi": "https://doi.org/{}",
    "bibcode": "https://ui.adsabs.harvard.edu/abs/{}",
}


def state_in(
    marks: DocumentMarks, corpus_root: Path, anchor: Path
) -> DocumentState | None:
    """One document's index state, or None when it cannot be checked."""
    if marks.states is None and not marks.never_indexed:
        return None
    return marks.state_of(corpus_root, anchor)


@dataclass(frozen=True, slots=True)
class ShownMatch:
    """A passage of this document the reader's words occur in."""

    label: str
    href: str


def shown_matches(
    chunks: Sequence[Chunk], *, question: str, collection: str, document_id: str
) -> tuple[ShownMatch, ...]:
    """The chunks the reader's words occur in, named by their section.

    The words are matched by the rule that marks them on the page, so a
    passage is listed exactly when it would show a mark.
    """
    pattern = query_pattern(terms_of(question))
    if pattern is None:
        return ()
    matching = [chunk for chunk in chunks if pattern.search(chunk.text)]
    in_section = Counter(chunk.section for chunk in matching if chunk.section)
    seen: Counter[str] = Counter()
    shown: list[ShownMatch] = []
    for chunk in matching:
        section = chunk.section
        if not section:
            label = words.passage_label(chunk.chunk_index)
        elif in_section[section] == 1:
            label = section
        else:
            seen[section] += 1
            label = words.match_in_section(section, seen[section], in_section[section])
        shown.append(
            ShownMatch(
                label=label,
                href=_href(collection, document_id, chunk.chunk_index, question),
            )
        )
    return tuple(shown)


def shown_document(
    corpus_root: Path,
    collection: str,
    document_id: str,
    *,
    load_remote_images: bool,
    marked: MarkedRange | None = None,
    marks: DocumentMarks | None = None,
    question: str = "",
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
    frontmatter = document.frontmatter
    anchor = _anchor(document)
    group = _group_of(corpus_root, collection, anchor)
    return ShownDocument(
        title=frontmatter.title,
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
            without_title=frontmatter.title,
            heading_anchors=True,
            terms=terms_of(question),
        ),
        has_blocked_images=_refers_remotely(document.body),
        group=group,
        handle=(
            frontmatter.bib.citekey
            if isinstance(frontmatter, LiteratureFrontmatter)
            else document.id
        ),
        byline=byline_of(frontmatter),
        details=document_details(
            frontmatter,
            collection=collection,
            group=group,
            state=None if marks is None else state_in(marks, corpus_root, anchor),
            original=_original_of(corpus_root, frontmatter),
        ),
        outline=tuple(headings_of(document.body, without_title=frontmatter.title)),
        other_versions=_other_versions(held, frontmatter),
    )


def _original_of(
    corpus_root: Path, frontmatter: DocumentFrontmatter
) -> tuple[str, str] | None:
    """The document a copy was made from and its page, or no link when it
    has gone; None when this is not a copy. Searched only for a copy,
    because finding an identifier lists each collection."""
    origin = frontmatter.source.origin
    if not origin.startswith(COPY_ORIGIN_SCHEME):
        return None
    identifier = origin.removeprefix(COPY_ORIGIN_SCHEME)
    for name in COLLECTION_NAMES:
        try:
            Collection(root=corpus_root, name=name).resolve(identifier)
        except DocumentNotFound:
            continue
        return identifier, f"/document/{name}/{identifier}"
    return identifier, ""


def _other_versions(
    held: Collection, frontmatter: DocumentFrontmatter
) -> tuple[tuple[str, str], ...]:
    """Where the same page is in the project's other versions.

    Linked by the identifier an add derives from the project, the version
    and the page, which is the one every copy was written under.
    """
    if not isinstance(frontmatter, DocsFrontmatter) or frontmatter.docs.version is None:
        return ()
    docs = frontmatter.docs
    return tuple(
        (
            version,
            "/document/docs/"
            + derive_id(
                natural_key_for_docs(
                    project=docs.project, version=version, page=docs.page
                )
            ),
        )
        for version in versions_holding(held.path, docs.project, docs.page)
        if version != docs.version
    )


def shown_bundle_document(
    bundle: Path,
    relative_path: str,
    *,
    project: str,
    load_remote_images: bool,
    marked: MarkedRange | None = None,
    question: str = "",
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
        # The project's group, so the page's own links name it too.
        collection=project_group(project),
        crumb_name=f"{project}/{bundle.name}",
        path=f"{bundle.name}/{relative_path}",
        body_html=to_html(
            body,
            load_remote_images=load_remote_images,
            marked=marked,
            without_title=str(title),
            heading_anchors=True,
            terms=terms_of(question),
        ),
        has_blocked_images=_refers_remotely(body),
        handle=relative_path,
        # A bundle note's frontmatter is the user's own and has no
        # model, so its details are where it is and nothing more.
        details=(
            ShownDetail(
                words.DETAIL_LABELS["collection"], group_name(project_group(project))
            ),
            ShownDetail(
                words.DETAIL_LABELS["path"],
                f"{bundle.name}/{relative_path}",
                verbatim=True,
            ),
        ),
        outline=tuple(headings_of(body, without_title=str(title))),
    )


def shown_pack_document(
    corpus_root: Path,
    pack_id: str,
    address: str,
    *,
    load_remote_images: bool,
    marked: MarkedRange | None = None,
    question: str = "",
) -> ShownDocument:
    """One of a pack's context files, as the store holds it (14g).

    Looked up among the files the pack declares, never joined onto a
    path, for the reason `shown_bundle_document` gives. Read only: the
    file is the pack's, and a project that wants its own version copies
    it with `kennis context copy`.
    """
    held = {one.state.pack_id: one for one in list_installed(corpus_root).packs}
    if pack_id not in held:
        raise PackNotInstalled(f"no pack '{pack_id}' is installed")
    file = pack_files(corpus_root, held[pack_id]).get(address)
    if file is None:
        raise DocumentNotFound(
            f"the pack '{pack_id}' ships no context file '{address}'",
            resolution=f"kennis pack status {pack_id}",
        )
    text = file.path.read_text(encoding="utf-8")
    try:
        frontmatter, body = split_frontmatter(text)
    except yaml.YAMLError:
        frontmatter, body = {}, text
    title = str(frontmatter.get("title") or Path(address).stem)
    return ShownDocument(
        title=title,
        document_id=address,
        collection=pack_group(pack_id),
        crumb_name=group_name(pack_group(pack_id)),
        crumb_href="/corpus#packs",
        path=f"{pack_id}/{address}",
        body_html=to_html(
            body,
            load_remote_images=load_remote_images,
            marked=marked,
            without_title=title,
            heading_anchors=True,
            terms=terms_of(question),
        ),
        has_blocked_images=_refers_remotely(body),
        handle=f"{pack_id}/{address}",
        details=(
            ShownDetail(
                words.DETAIL_LABELS["collection"], group_name(pack_group(pack_id))
            ),
            ShownDetail(
                words.DETAIL_LABELS["copy"],
                f"kennis context copy {pack_id}/{address}",
                verbatim=True,
            ),
        ),
        outline=tuple(headings_of(body, without_title=title)),
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
    "ShownDetail",
    "ShownDocument",
    "ShownEntry",
    "ShownGroup",
    "ShownHit",
    "ShownKey",
    "ShownKeyLine",
    "ShownMark",
    "ShownMatch",
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
    "byline_of",
    "document_details",
    "every_level",
    "known_groups",
    "ordered_by",
    "palette_entries",
    "palette_typed",
    "shown_backup",
    "shown_bundle_document",
    "shown_document",
    "shown_groups",
    "shown_groups_of",
    "shown_hits",
    "shown_key",
    "shown_matches",
    "shown_measures",
    "shown_orders",
    "shown_rows",
    "shown_skips",
    "shown_tree",
    "state_in",
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
    context: Context, collection: str
) -> tuple[list[tuple[str, list[ShownEntry]]], int]:
    """A collection's documents by group, and how many could not be read.

    Grouped by the directory a document sits in, which is what the
    corpus layout means by a group - `corpus tree` shows the same
    shape. The ungrouped ones come first under an empty name, because
    a collection with no groups should not lead with a heading.
    """
    corpus_root = context.corpus_root
    contents = contents_of(context, collection)
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


def known_groups(context: Context, collections: Sequence[str]) -> list[str]:
    """Every group already held in `collections`, for a typed group field
    to suggest: typed free, "Radio" beside "radio" quietly made a second
    group. Read through the same cached contents the pane draws from."""
    root = context.corpus_root
    found: set[str] = set()
    for collection in collections:
        for document in contents_of(context, collection).documents:
            group = _group_of(root, collection, _anchor(document))
            if group:
                found.add(group)
    return every_level(found)


def every_level(groups: Iterable[str]) -> list[str]:
    """Each group and every group it is inside, once each, sorted: a
    folder holding only folders is a group to file into too."""
    levels: set[str] = set()
    for group in groups:
        parts = group.split("/")
        levels.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    levels.discard("")
    return sorted(levels)


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
    "search": "query",
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
    # Drawn hidden and shown only once something typed matches it: a
    # document or a past search. Every action shows on an empty palette;
    # a thousand titles would bury them.
    typed_only: bool = False
    # A document's collection, whose colour it wears in place of a role,
    # as it does on a card and in the pane.
    collection: str = ""

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


def palette_typed(
    context: Context, searches: Sequence[Search]
) -> list[ShownPaletteEntry]:
    """Documents by title and past searches, for the palette to find.

    It found only actions and places, so "bandpass" answered "Nothing
    matches" with a document of that name in the corpus (the flows
    review, F7). Read through `contents_of`, which is cached against the
    corpus state, so opening the palette walks nothing that has not
    changed. A collection that cannot be read is left out, not raised:
    the palette is a convenience, and the pane says what is wrong.
    """
    entries: list[ShownPaletteEntry] = []
    for search in searches:
        entries.append(
            ShownPaletteEntry(
                label=search.query,
                href=f"/?q={quote(search.query)}&scope={quote(search.scope)}"
                + (f"&mode={quote(search.mode)}" if search.mode else ""),
                kind=words.PALETTE_KINDS["search"],
                icon="history",
                role=PALETTE_ROLES["search"],
                match=f"{search.query} {words.PALETTE_KINDS['search']}".casefold(),
                typed_only=True,
            )
        )
    for collection in COLLECTION_NAMES:
        try:
            contents = contents_of(context, collection)
        except KennisError:
            continue
        for document in sorted(contents.documents, key=_sort_key):
            title = document.frontmatter.title
            entries.append(
                ShownPaletteEntry(
                    label=title,
                    href=f"/document/{collection}/{document.id}",
                    kind=collection,
                    icon=words.COLLECTION_ICONS[collection],
                    role="",
                    match=f"{title} {collection}".casefold(),
                    typed_only=True,
                    collection=collection,
                )
            )
    return entries


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
    """One group: its own entries, the groups inside it, and the worst
    state anywhere beneath it.

    `group` is the whole path, which is what Add here, the Move field and
    `data-group` name; `name` is its last part, which is what the folder
    is called where it is drawn. `group` is empty for the collection's own
    top level, which is drawn without a heading.
    """

    group: str
    entries: list[ShownTreeEntry]
    mark: ShownMark | None
    add_here: str
    children: list[ShownBranch]
    count: int
    # For a docs version's folder (#489): its project and version, and
    # whether a search uses it by default. Empty for any other group.
    project: str = ""
    version: str = ""
    current: bool = False

    @property
    def name(self) -> str:
        return self.group.rpartition("/")[2]

    @property
    def state(self) -> str:
        return self.mark.state if self.mark else ""

    def beneath(self) -> list[ShownTreeEntry]:
        """Every entry in this group and in every group inside it."""
        return self.entries + [
            entry for child in self.children for entry in child.beneath()
        ]


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
    contents = contents_of(context, collection)
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
    levels = every_level(grouped)
    held = (
        project_versions(Collection(root=root, name="docs").path)
        if collection == "docs"
        else {}
    )
    top = _branch(collection, "", grouped, levels, held)
    every = top.beneath()
    return ShownTree(
        collection=collection,
        top=replace(top, children=[]),
        branches=top.children,
        groups=levels,
        attention=sum(1 for entry in every if entry.mark),
        movable=collection != "docs",
    )


def _branch(
    collection: str,
    group: str,
    grouped: dict[str, list[ShownTreeEntry]],
    levels: list[str],
    held: Mapping[str, ProjectVersions],
) -> ShownBranch:
    """`group` and, drawn inside it, every group one level down."""
    children = [
        _branch(collection, level, grouped, levels, held)
        for level in levels
        if level.rpartition("/")[0] == group
    ]
    project, _, version = group.partition("/")
    versions = held.get(project)
    is_version = versions is not None and version in versions.held
    entries = grouped.get(group, [])
    beneath = entries + [entry for child in children for entry in child.beneath()]
    attention = [entry.state for entry in beneath if entry.mark]
    worst = next((state for state in STATE_ORDER if state in attention), "")
    return ShownBranch(
        group=group,
        entries=entries,
        mark=_mark(worst, words.attention_count(len(attention))) if worst else None,
        add_here=add_here_address(collection, group),
        children=children,
        count=len(beneath),
        project=project if is_version else "",
        version=version if is_version else "",
        current=is_version and versions is not None and versions.current == version,
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
    # What else the write did that the reader should know of: documents
    # deleted by hand that it put back.
    notes: tuple[str, ...] = ()
    # The collection to offer an Index now button for, when what was
    # written cannot be found until it is indexed.
    index_after: str | None = None


@dataclass(frozen=True, slots=True)
class ShownItem:
    """One item an operation touched, and why where there is a why.

    `repairs` and `ways` are empty except on a refusal the interface can
    actually act on: a form to post, and a place to go. An offer that
    cannot work is worse than none.
    """

    marker: str
    name: str
    outcome: str
    detail: str | None = None
    remedies: tuple[str, ...] = ()
    repairs: tuple[Repair, ...] = ()
    ways: tuple[WayOut, ...] = ()

    @property
    def asks(self) -> bool:
        """Whether it offers the reader something to do about it."""
        return bool(self.remedies or self.repairs or self.ways)


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
    # Parts of the page the outcome changes, as (element id, route that
    # draws it). The outcome asks for each again on arrival, where the
    # page has one: a backup's section otherwise kept saying no backup
    # had been written while the strip beside it said one had. The
    # strip's status and the pane are added for every job (#457).
    redraws: tuple[tuple[str, str], ...] = ()
    # Whether the outcome offers to index what it wrote: "Not searchable
    # until the index is rebuilt" was a sentence with nothing to press.
    index_after: bool = False
    # Whether to offer the syncs, after an install that brought nothing
    # into the corpus yet.
    sync_after: bool = False

    @property
    def single(self) -> tuple[ShownItem, ...]:
        """The items with a way out of their own - a repair or a command -
        which are drawn one by one and first, because each asks something."""
        return tuple(item for item in self.items if item.asks)

    @property
    def groups(self) -> tuple[OutcomeGroup, ...]:
        """Every other item, grouped by what happened and why, failures first.

        A docs add with eight pages refused for one reason drew eight red
        lines naming each page twice (Brian, 2026-10-16); one reason is one
        group, and a page of them reads as what it is.
        """
        grouped: dict[tuple[str, str], list[ShownItem]] = {}
        for item in self.items:
            if item.asks:
                continue
            grouped.setdefault((item.outcome, item.detail or ""), []).append(item)
        groups = [
            OutcomeGroup(outcome=outcome, reason=reason, items=tuple(items))
            for (outcome, reason), items in grouped.items()
        ]
        return tuple(sorted(groups, key=lambda group: group.outcome != "failed"))


@dataclass(frozen=True, slots=True)
class OutcomeGroup:
    """Items an operation treated alike: one outcome, one reason."""

    outcome: str
    reason: str
    items: tuple[ShownItem, ...]

    @property
    def label(self) -> str:
        """The reason they share, or what happened when there is none."""
        said = self.reason or words.OUTCOME_WORDS.get(self.outcome, self.outcome)
        return said[:1].upper() + said[1:]

    @property
    def marker(self) -> str:
        return self.items[0].marker

    @property
    def base(self) -> str:
        """The folder the names share, said once above them; empty when
        they share none, or when there is one name."""
        if len(self.items) < 2:
            return ""
        shared = os.path.commonprefix([item.name for item in self.items])
        return shared[: shared.rfind("/") + 1]

    def short(self, item: ShownItem) -> str:
        """An item's name beneath its group's base."""
        return item.name[len(self.base) :]


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
        index_after=bool(added),
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
    ways = ways_out_for(outcome.refusal)
    # The window's words: the terminal's sentence ends in flags to type,
    # and here each way out is a control instead (#475).
    return replace(
        shown,
        detail=refusal_fact(outcome.refusal),
        repairs=repairs,
        ways=ways,
        remedies=() if repairs or ways else remedies_for_refusal(outcome.refusal),
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
    if result.copied:
        notes.append(describe_kept_copies(len(result.copied)))
        notes.extend(
            describe_kept_copy(original, copy) for original, copy in result.copied
        )
    if result.failed:
        notes.append(describe_unfetched(result.failed))
        notes.extend(
            describe_why_unfetched(address, refusal) for address, refusal in result.why
        )
    if result.deferred:
        notes.append(describe_deferred(result.deferred))
    acted = any(action.verdict in ACTING for action in result.actions)
    if acted:
        notes.append(words.NOT_SEARCHABLE_YET)
    return ShownJob(
        headline=capitalised(describe_sync(result.counts, noun="document")),
        role="role-added" if acted else "role-muted",
        items=tuple(
            ShownItem(
                marker=SYNC_MARKERS.get(action.verdict, ">"),
                # Where the document is, not the pack's address for it.
                name=result.places.get(action.address, action.address),
                outcome=action.verdict,
                detail=describe_outcome_of(action),
            )
            for action in result.actions
        ),
        notes=tuple(notes),
        next_steps=tuple(steps),
        index_after=acted,
    )


def capitalised(said: str) -> str:
    """A line of the render layer's, as a headline: it starts a sentence."""
    return said[:1].upper() + said[1:]


def shown_bundle_sync(result: BundleSync) -> ShownJob:
    """A context sync. No commit happened and the page has to say so."""
    notes: list[str] = [words.BUNDLE_NOT_COMMITTED]
    if result.made_yours:
        notes.append(describe_made_yours())
    if result.declared:
        notes.append(describe_declared(result.declared))
    if result.missing:
        notes.append(describe_not_installed(result.missing))
    if not result.declared and not result.missing:
        notes.append(describe_no_declaration())
    acted = bool(result.removed or result.made_yours)
    return ShownJob(
        headline=capitalised(
            describe_bundle_sync(len(result.removed), len(result.made_yours))
        ),
        role="role-added" if acted else "role-muted",
        items=(
            *(
                ShownItem(marker="-", name=address, outcome="removed")
                for address in result.removed
            ),
            *(
                ShownItem(marker="~", name=address, outcome="made yours")
                for address in result.made_yours
            ),
        ),
        notes=tuple(notes),
        # `kennis context index` stays a command, unlike the corpus
        # one: this interface has no control that indexes a bundle, so
        # the terminal really is where that is done.
        next_steps=("kennis context index",) if acted else (),
    )


def shown_backup(report: BackupReport) -> ShownJob:
    """A backup: where it was written, how large, and how many entries."""
    return ShownJob(
        headline=f"Backed up to {describe_written(report)}",
        redraws=(("backup", "/settings/backup"),),
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
        # Buttons, not the two commands: this window has both syncs.
        sync_after=True,
    )
