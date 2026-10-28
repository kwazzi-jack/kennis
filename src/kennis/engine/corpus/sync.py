"""`corpus sync`: converging the corpus with every installed pack.

Design section 5, steps 4, 4a and 6, against the second destination. The
table is `engine/pack/resolve.py` and is not repeated here; what differs
is the two functions either side of it.

**A corpus document is not addressed by where it lives.** Its filename
comes from its title and its identity is a minted surrogate identifier
that every read handle depends on, so the address a pack declared has to
be recorded *in* the document - `source.from: pack:<id>/<address>`. A
sync that could not find the document it wrote last time would write a
second one on every run, and re-minting the identifier would break every
handle pointing at the first.

**Two digests, for the same reason the bundle needs two.** `sha256` is
the body kennis wrote, which a user edit moves; `pack_sha256` is the
store file it came from, which a provider release moves. A pack file
carrying its own frontmatter has that header read and replaced, so the
two are different bytes and one value cannot answer both questions.

**This module writes and does not commit.** The corpus is kennis's own
repository and every mutation is committed by its command, once per
invocation - so the caller holding the lock decides what history records.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

import httpx

from kennis.engine.cancelling import pause
from kennis.engine.corpus.add import (
    ARXIV_DELAY_SECONDS,
    AddOptions,
    AddReport,
    Uniqueness,
    add_docs,
    add_literature,
    write_note,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.copying import copied_note
from kennis.engine.corpus.document import (
    Document,
    move_document,
    remove_empty_groups,
    write_document,
)
from kennis.engine.corpus.intake import Converted, convert_local_file, convert_url
from kennis.engine.corpus.layout import iter_documents, relative_to_corpus
from kennis.engine.corpus.moving import holding, move_target
from kennis.engine.corpus.schema import (
    Bibliography,
    DocsFrontmatter,
    LiteratureFrontmatter,
    NoteFrontmatter,
    Source,
    SourceFormat,
)
from kennis.engine.docs.versions import removed_version, version_in_address
from kennis.engine.errors import DocumentInvalid, InputError, KennisError
from kennis.engine.events import (
    Event,
    EventSink,
    ItemFinished,
    OperationFinished,
    Outcome,
    Progress,
)
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.groups import group_directory
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import (
    InstalledPack,
    declared_content,
    list_installed,
    refuse_damaged_packs,
)
from kennis.engine.pack.resolve import Action, Declaration, Existing, Verdict, resolve
from kennis.engine.pack.schema import (
    DocsEntry,
    LiteratureEntry,
    NoteFile,
    NoteLink,
    Pack,
)
from kennis.engine.pack.store import pack_root
from kennis.engine.refusals import Quoted, Refusal
from kennis.engine.remember import title_for

OPERATION = "corpus-sync"

# The `source.from` scheme that says a pack supplied this document. The
# rest of the value is `<pack id>/<address>`, which is what makes the
# document findable again by the address rather than by its path.
ORIGIN_SCHEME = "pack:"

_OUTCOMES: dict[Verdict, Outcome] = {
    "write": Outcome.ADDED,
    "rewrite": Outcome.CHANGED,
    "adopt": Outcome.CHANGED,
    "delete": Outcome.REMOVED,
    "keep": Outcome.UNCHANGED,
    # The original is the pack's again, and the edit is a new note.
    "edited": Outcome.CHANGED,
    "yours": Outcome.SKIPPED,
}


@dataclass(frozen=True, slots=True)
class CorpusSync:
    """What one `corpus sync` did, by verdict.

    `copied` pairs each pack note the person had edited with the note of
    theirs the edit now lives in, `(original, copy)` by identifier: the
    original was put back from the pack, or removed if the pack no longer
    declares it, and no edit is lost (14g, #514).
    """

    actions: tuple[Action, ...]
    counts: dict[Verdict, int]
    deferred: tuple[tuple[str, str], ...]
    copied: tuple[tuple[str, str], ...]
    # Declarations whose fetch did not succeed. Not a verdict: the
    # declaration still stands and the document is still absent, so the
    # next run tries again. One unreachable host must not stop the other
    # nine papers from arriving.
    failed: tuple[str, ...] = ()
    # Why each paper in `failed` was not fetched, where the add said: a
    # paper with no copy kennis can reach names where to get one, and a
    # sync that kept that to itself left the reader nothing to do but wait
    # for a next run that would fail the same way.
    why: tuple[tuple[str, Refusal], ...] = ()
    # Where each address's document is, relative to the corpus root:
    # after the sync, or where it was for one removed. An address is the
    # pack's name for a document - `c.md` inside its notes source,
    # `arxiv:2409.19750` - and a report naming it told the reader nothing
    # about their corpus (Brian, 2026-10-16). An address with no document
    # either side, a fetch that failed, has no place.
    places: dict[str, str] = field(default_factory=dict)


def sync_corpus(
    corpus_root: Path,
    *,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    client: httpx.Client | None = None,
    request_delay_seconds: float | None = None,
    unpaywall_email: str = "",
    store_root: Path | None = None,
) -> CorpusSync:
    """Converge the corpus with every installed pack.

    `store_root` is the corpus whose pack store is read, when the
    collections at `corpus_root` are a mirror of it being prepared
    (`engine/staging.py`); the corpus itself by default.

    Three sections, resolved by the same table and materialised three
    ways: notes are copied out of the store, papers are fetched by
    identifier and documentation projects are crawled.

    **The clients are arguments.** An engine that reached for its own
    transport is an engine two callers cannot use differently in one
    process, and a test that could not supply one would have to reach a
    host. Concern #87.

    Raises `PackInvalid` while any installed pack is damaged, and
    `DocumentInvalid` for an `owner` kennis does not recognise. Both are
    raised before anything is written or fetched.
    """
    started = time.monotonic()
    store = store_root or corpus_root
    packs = list_installed(store).packs
    refuse_damaged_packs(packs)

    notes = _notes_plan(corpus_root, store, packs)
    papers = _literature_plan(corpus_root, packs)
    projects = _docs_plan(corpus_root, packs)
    _refuse_what_cannot_be_classified(notes, papers, projects)
    notes = _relocated(Collection(root=corpus_root, name="notes"), notes)
    papers = _relocated(Collection(root=corpus_root, name="literature"), papers)

    why: dict[str, Refusal] = {}
    copied: list[tuple[str, str]] = []
    failed = _carried_out(
        corpus_root,
        notes,
        papers,
        projects,
        store=store,
        arxiv=arxiv,
        client=client,
        request_delay_seconds=request_delay_seconds,
        unpaywall_email=unpaywall_email,
        events=events,
        why=why,
        copied=copied,
    )

    actions = notes.actions + papers.actions + projects.actions
    counts = Counter(action.verdict for action in actions)
    places = _places(corpus_root, notes, papers, projects)
    _reported(events, actions, places, started)
    return CorpusSync(
        actions=actions,
        counts=dict(counts),
        deferred=notes.deferred,
        copied=tuple(copied),
        failed=failed,
        why=tuple(why.items()),
        places=places,
    )


def supply_paper(
    corpus_root: Path,
    address: str,
    path: Path,
    *,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    client: httpx.Client | None = None,
    store_root: Path | None = None,
) -> AddReport:
    """Add the paper a pack declares at `address` from a file the person
    supplied, because no copy kennis may fetch exists (Brian, 2026-10-26).

    Filed as the sync would have filed the fetched text - the declaring
    pack's owner and digest, its citekey and group - so the next sync finds
    it held at that digest and keeps it. The pack owns it, so it goes with
    the pack's other papers. `store_root` is as for `sync_corpus`.

    Raises `InputError` when no installed pack declares `address`, or the
    corpus holds that paper already.
    """
    store = store_root or corpus_root
    packs = list_installed(store).packs
    refuse_damaged_packs(packs)
    plan = _literature_plan(corpus_root, packs)
    declaration = plan.declarations.get(address)
    if declaration is None:
        raise InputError(f"no installed pack declares {address}")
    if address in plan.held:
        raise InputError(f"the corpus already holds {address}")
    entry = plan.entries[address]
    assert isinstance(entry, LiteratureEntry)
    return add_literature(
        Collection(root=corpus_root, name="literature"),
        [str(path)],
        AddOptions(
            identifier=entry.identifier or entry.paper.value,
            citekey=entry.citekey,
            group=_paper_group(declaration, entry),
            owner=f"pack:{declaration.pack_id}",
            pack_sha256=declaration.digest,
        ),
        arxiv=arxiv,
        client=client,
        events=events,
    )


def _places(
    corpus_root: Path, notes: _Plan, papers: _Plan, projects: _Plan
) -> dict[str, str]:
    """Where each action's document is now, or was before a delete.

    Notes and papers are found again after carrying out, by the keys their
    plans use, because a write files a document and a relocation moves one.
    A docs project is its folder.
    """
    places: dict[str, str] = {}
    sections = (
        (notes, _held(Collection(root=corpus_root, name="notes"))),
        (papers, _held_papers(Collection(root=corpus_root, name="literature"))),
    )
    for plan, now in sections:
        for action in plan.actions:
            found = now.get(action.address) or plan.held.get(action.address)
            if found is not None:
                places[action.address] = relative_to_corpus(
                    found[1].md_path, corpus_root
                )
    for action in projects.actions:
        places[action.address] = f"docs/{action.address}"
    return places


# A declaration whose content is the entry itself rather than a file.
type Entry = LiteratureEntry | DocsEntry | NoteLink | NoteFile


@dataclass(frozen=True, slots=True)
class _Plan:
    """One section's resolution, with what it was resolved against.

    `held` keeps the documents beside the `Existing` values the table
    saw, because carrying out an action needs the document and the table
    does not.
    """

    actions: tuple[Action, ...]
    held: dict[str, tuple[Existing, Document]]
    declarations: dict[str, Declaration]
    # Documents in this collection that would not validate. They are
    # invisible to the table - an unreadable document is not in
    # `contents().documents` - so a sync that ignored them would see
    # their declarations as unfetched and write a second copy of each.
    unreadable: tuple[str, ...] = ()
    # The declaration entries themselves, for the two sections whose
    # content is the entry rather than a file: a fetch needs the base
    # url and a rename needs the bib fields, and a digest carries
    # neither. For notes, only the ones declared by address (#459): the
    # rest are in the store.
    entries: dict[str, Entry] = field(default_factory=dict)
    deferred: tuple[tuple[str, str], ...] = ()


def _refuse_what_cannot_be_classified(*plans: _Plan) -> None:
    """Section 6: corruption is refused with the document named.

    Two ways a document defeats the table, and they have to be caught
    together because the second is the dangerous one.

    An `owner` kennis does not recognise reaches the table and comes
    back as `refuse`. A document that will not **validate at all** never
    reaches it: `contents()` puts it in `unreadable`, so its declaration
    looks unfetched and a sync that ignored it would write a second
    copy of the same paper - and an `owner` of `managed_by:boepie` fails
    validation, so that is the ordinary case rather than an exotic one.
    Concern #278.

    Every one of them at once, and before anything is written or
    fetched: a user with three corrupt documents is better served by
    three names than by three runs, and a half-converged corpus is
    worse than an unconverged one.
    """
    named = sorted(
        [
            action.address
            for plan in plans
            for action in plan.actions
            if action.verdict == "refuse"
        ]
        + [name for plan in plans for name in plan.unreadable]
    )
    if not named:
        return
    raise DocumentInvalid(
        "these documents could not be classified, so nothing has been "
        f"synchronised: {', '.join(named)}",
        resolution="kennis corpus status",
    )


# The verdicts that leave a pack's document standing as the pack's. Not
# `edited`, which is rewritten in place this run and stands from the next.
_STANDING: Final = frozenset({"keep", "rewrite", "adopt"})


def _relocated(collection: Collection, plan: _Plan) -> _Plan:
    """Move each standing pack document into the folder it is declared in.

    A pack's notes and papers are filed under the pack's id (Brian,
    2026-10-16), and `resolve` keys them by address, never by path, so a
    document somewhere else - written before that decision, or under a
    group the pack has since changed - is the same document in the wrong
    place. It is moved at its identifier, body and filename, and the plan
    is returned with the moved document held, so a rewrite that follows
    writes where it now is. A `keep` that moved becomes a `rewrite`: the
    disk changed, and "unchanged" would say it had not.
    """
    held = dict(plan.held)
    actions: list[Action] = []
    for action in plan.actions:
        declaration = action.declaration
        if action.verdict not in _STANDING or declaration is None:
            actions.append(action)
            continue
        existing, document = held[action.address]
        group = _declared_group(plan, declaration)
        if (
            holding(document).resolve()
            == group_directory(collection.path, group).resolve()
        ):
            actions.append(action)
            continue
        target = move_target(collection, document, group=group, title=None)
        if target.exists() or (target.parent / target.stem).exists():
            target = move_target(
                collection, document, group=group, title=document.frontmatter.title
            )
        moved_from = holding(document)
        held[action.address] = (
            existing,
            move_document(document, target_md_path=target),
        )
        remove_empty_groups(moved_from, collection=collection.path)
        actions.append(
            replace(action, verdict="rewrite") if action.verdict == "keep" else action
        )
    return replace(plan, actions=tuple(actions), held=held)


def _declared_group(plan: _Plan, declaration: Declaration) -> str:
    """The folder a pack's document is declared in, inside its collection:
    the pack's id, then a paper's `group`, or a note's address's folders."""
    entry = plan.entries.get(declaration.address)
    if isinstance(entry, LiteratureEntry):
        return _paper_group(declaration, entry)
    if isinstance(entry, (NoteLink, NoteFile)):
        return "/".join(part for part in (declaration.pack_id, entry.group) if part)
    return _note_group(declaration)


def _paper_group(declaration: Declaration, entry: LiteratureEntry) -> str:
    """Where a pack's paper is filed: under the pack, in its `group`."""
    return "/".join(part for part in (declaration.pack_id, entry.group) if part)


def _unreadable_in(collection: Collection) -> tuple[str, ...]:
    """The names of documents in this collection that will not validate."""
    return tuple(
        sorted(facts.md_path.name for facts in collection.contents().unreadable)
    )


def _notes_plan(
    corpus_root: Path, store: Path, packs: tuple[InstalledPack, ...]
) -> _Plan:
    """The store's notes and the ones declared by address, resolved together.

    One table for both, because both are notes a pack owns and `_held`
    finds either by the address in its `source.from`. A link's address is
    marked `url:`, so it cannot be a file's path in the store.
    """
    union = declared_content(store, packs, "notes")
    declarations = dict(union.declarations)
    deferred = list(union.deferred)
    entries: dict[str, Entry] = {}
    ordered = sorted(
        packs, key=lambda one: (one.state.first_applied_at, one.state.pack_id)
    )
    for one in ordered:
        if one.declaration is None:
            continue
        for note in one.declaration.corpus.note_links:
            if note.key in declarations:
                if declarations[note.key].pack_id != one.state.pack_id:
                    deferred.append((note.key, one.state.pack_id))
                continue
            declarations[note.key] = Declaration(
                address=note.key,
                pack_id=one.state.pack_id,
                digest=_link_digest(note),
                store_path=None,
            )
            entries[note.key] = note
        for shipped in one.declaration.corpus.note_files:
            if shipped.key in declarations:
                if declarations[shipped.key].pack_id != one.state.pack_id:
                    deferred.append((shipped.key, one.state.pack_id))
                continue
            declarations[shipped.key] = Declaration(
                address=shipped.key,
                pack_id=one.state.pack_id,
                digest=_file_digest(shipped, one.state.files),
                store_path=pack_root(store, one.state.pack_id) / shipped.file,
            )
            entries[shipped.key] = shipped
    collection = Collection(root=corpus_root, name="notes")
    held = _held(collection)
    return _Plan(
        actions=resolve(declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=declarations,
        unreadable=_unreadable_in(collection),
        entries=entries,
        deferred=tuple(sorted(deferred)),
    )


def _carried_out(
    corpus_root: Path,
    notes: _Plan,
    papers: _Plan,
    projects: _Plan,
    *,
    store: Path,
    arxiv: httpx.Client | None,
    client: httpx.Client | None,
    request_delay_seconds: float | None,
    unpaywall_email: str,
    events: EventSink | None,
    why: dict[str, Refusal],
    copied: list[tuple[str, str]],
) -> tuple[str, ...]:
    """Do what the three plans decided, and report what would not happen.

    Notes first, because most of them cannot fail: copying out of a
    verified store either works or the store was damaged, and that was
    refused before this was called. A note declared by address, or a
    shipped file kennis converts, can fail (#459), and fails alone. The
    two that reach a host go afterwards, so an unreachable one leaves a
    corpus that is otherwise converged.
    """
    collection = Collection(root=corpus_root, name="notes")
    record = Uniqueness.of(collection)
    failed_notes: list[str] = []
    for action in notes.actions:
        try:
            if action.verdict == "edited":
                copied.append(
                    _kept_as_theirs(collection, record, action, notes, client)
                )
                continue
            _applied(collection, record, action, notes, client)
        except KennisError as error:
            failed_notes.append(action.address)
            why[action.address] = Quoted(str(error))

    progress = _Progress(
        events,
        total=sum(1 for action in papers.actions if action.verdict == "write")
        + sum(1 for action in projects.actions if action.verdict in _CRAWLED),
    )
    failed = failed_notes + list(
        _fetched_literature(
            corpus_root,
            papers,
            store=store,
            arxiv=arxiv,
            client=client,
            request_delay_seconds=request_delay_seconds,
            unpaywall_email=unpaywall_email,
            events=events,
            progress=progress,
            why=why,
        )
    )
    failed.extend(
        _crawled_docs(
            corpus_root,
            projects,
            store=store,
            client=client,
            # The figure is arXiv's pacing; a docs host gets its own
            # default. Zero still passes: it is a caller that contacts
            # nothing.
            request_delay_seconds=0.0 if request_delay_seconds == 0 else None,
            events=events,
            progress=progress,
        )
    )
    return tuple(failed)


# The docs verdicts that crawl.
_CRAWLED: Final = frozenset({"write", "rewrite", "adopt"})


class _Progress:
    """One bar for the whole sync, a step per paper and per project.

    The papers and the crawls are the part that takes minutes, and they drew
    nothing: an add of one paper emits no progress of its own, a crawl's
    first comes only once its discovery is done, and each add's
    `OperationFinished` closed whatever bar was open. A sync that had
    written its notes then sat silent until it was interrupted.
    """

    def __init__(self, events: EventSink | None, *, total: int) -> None:
        self._events = events
        self._total = total
        self._completed = 0
        if total:
            self._emit()

    @property
    def inner(self) -> EventSink | None:
        """The sink an add inside the sync reports through: everything but
        its own bar and its own finish, which are the sync's to draw."""
        return None if self._events is None else _WithoutBars(self._events)

    def step(self) -> None:
        self._completed += 1
        self._emit()

    def _emit(self) -> None:
        if self._events is not None and self._total:
            self._events.emit(
                Progress(
                    operation=OPERATION, completed=self._completed, total=self._total
                )
            )


@dataclass(frozen=True, slots=True)
class _WithoutBars:
    events: EventSink

    def emit(self, event: Event) -> None:
        if isinstance(event, Progress | OperationFinished):
            return
        self.events.emit(event)


def _fetched_literature(
    corpus_root: Path,
    plan: _Plan,
    *,
    store: Path,
    arxiv: httpx.Client | None,
    client: httpx.Client | None,
    request_delay_seconds: float | None,
    unpaywall_email: str,
    events: EventSink | None,
    progress: _Progress,
    why: dict[str, Refusal],
) -> list[str]:
    """Fetch the papers that are missing, rewrite the ones that moved.

    A `rewrite` never refetches. Section 5 step 3 makes a changed
    citekey against an unchanged identifier a rename, so the bib fields
    are replaced in place and the document, its identifier and its text
    are left alone.
    """
    collection = Collection(root=corpus_root, name="literature")
    failed: list[str] = []
    # Paced here, between papers: each is its own add of one, so the add's
    # own pacing - between the papers it is given - never came into play,
    # and a sync asked arXiv for every paper back to back.
    delay = (
        ARXIV_DELAY_SECONDS if request_delay_seconds is None else request_delay_seconds
    )
    fetched = 0
    for action in plan.actions:
        declaration = action.declaration
        if action.verdict == "delete":
            _removed(collection, plan.held[action.address][1])
            continue
        if action.verdict in {"rewrite", "adopt"} and declaration is not None:
            _rewrote_bibliography(
                plan.held[action.address][1], declaration, plan.entries
            )
            continue
        if action.verdict != "write" or declaration is None:
            continue
        entry = plan.entries[action.address]
        assert isinstance(entry, LiteratureEntry)
        if fetched and delay:
            pause(delay)
        fetched += 1
        # The pack's copy of the paper when it ships one; the address, when
        # it gives one, read as the paper the identifier names; otherwise
        # the identifier, fetched as it is.
        if entry.file is not None:
            source = str(pack_root(store, declaration.pack_id) / entry.file)
        elif entry.url is not None:
            source = entry.url
        else:
            source = action.address
        report = add_literature(
            collection,
            [source],
            AddOptions(
                identifier=entry.identifier if source != action.address else None,
                # The pack's citekey, not a derived one. It is the handle
                # the provider's own prose cites, so a document that
                # arrived under a citekey kennis invented would answer to
                # nothing the pack says.
                citekey=entry.citekey,
                group=_paper_group(declaration, entry),
                owner=f"pack:{declaration.pack_id}",
                pack_sha256=declaration.digest,
                pack_store=pack_root(store, declaration.pack_id),
                request_delay_seconds=request_delay_seconds,
                unpaywall_email=unpaywall_email,
            ),
            arxiv=arxiv,
            client=client,
            events=progress.inner,
        )
        progress.step()
        if not any(one.outcome is Outcome.ADDED for one in report.outcomes):
            failed.append(action.address)
            refusal = next(
                (one.refusal for one in report.outcomes if one.refusal is not None),
                None,
            )
            if refusal is not None:
                why[action.address] = refusal
    return failed


def _crawled_docs(
    corpus_root: Path,
    plan: _Plan,
    *,
    store: Path,
    client: httpx.Client | None,
    request_delay_seconds: float | None,
    events: EventSink | None,
    progress: _Progress,
) -> list[str]:
    """Crawl the versions that are missing, drop the ones that went.

    **`keep` does not re-crawl.** A crawl is hundreds of requests, and
    refreshing a site is the reader's decision, made with `corpus add -d
    --refresh` (#277, #489). A plain add of a held site writes nothing.

    A delete removes every page a pack holds of that version of the
    project, because the unit of declaration is the version (Brian,
    2026-10-28); leaving some would leave a version nothing declares and
    nothing would ever clean. Its folder goes when that empties it.
    """
    collection = Collection(root=corpus_root, name="docs")
    failed: list[str] = []
    for action in plan.actions:
        declaration = action.declaration
        if action.verdict == "delete":
            held = plan.held[action.address][1].frontmatter
            assert isinstance(held, DocsFrontmatter)
            _dropped_version(collection, held.docs.project, held.docs.version)
            continue
        if action.verdict not in _CRAWLED:
            continue
        if declaration is None:
            continue
        entry = plan.entries[action.address]
        assert isinstance(entry, DocsEntry)
        # A site is crawled from its address; local pages are read from the
        # pack's copies in the store.
        sources = (
            [entry.base_url]
            if entry.base_url is not None
            else [
                str(pack_root(store, declaration.pack_id) / page)
                for page in entry.pages
            ]
        )
        report = add_docs(
            collection,
            sources,
            AddOptions(
                project=entry.project,
                version=entry.version,
                exclude=tuple(entry.exclude),
                owner=f"pack:{declaration.pack_id}",
                pack_sha256=declaration.digest,
                pack_store=pack_root(store, declaration.pack_id),
                # A held local page is otherwise reported unchanged and kept
                # as it was, so a page the provider changed never arrived.
                refresh=entry.base_url is None,
                request_delay_seconds=request_delay_seconds,
            ),
            client=client,
            events=progress.inner,
        )
        progress.step()
        # Every page, including those the crawl found already held: they
        # kept the old owner and digest, so the next sync judged the
        # project changed again and crawled it again, every time.
        _stamped_version(
            collection, entry.project, _declared_version(entry), declaration
        )
        if not any(
            one.outcome in (Outcome.ADDED, Outcome.UNCHANGED) for one in report.outcomes
        ):
            failed.append(action.address)
    return failed


def _stamped_version(
    collection: Collection,
    project: str,
    version: str | None,
    declaration: Declaration,
) -> None:
    """Mark the pages of one version of `project` as the declaring pack's,
    at its digest. Never a page of the person's: one they added into a
    pack's version is still theirs, and stamping it would let the pack
    remove it later."""
    owner = f"pack:{declaration.pack_id}"
    for document in _pages_of(collection, project, version):
        frontmatter = document.frontmatter
        assert isinstance(frontmatter, DocsFrontmatter)
        if frontmatter.owner == "user":
            continue
        if (
            frontmatter.owner == owner
            and frontmatter.source.pack_sha256 == declaration.digest
        ):
            continue
        updated = frontmatter.model_copy(
            update={
                "owner": owner,
                "source": frontmatter.source.model_copy(
                    update={"pack_sha256": declaration.digest}
                ),
            }
        )
        write_document(document.md_path, frontmatter=updated, body=document.body)


def _pages_of(
    collection: Collection, project: str, version: str | None
) -> list[Document]:
    """Every page of one version of `project`."""
    return [
        document
        for document in collection.contents().documents
        if isinstance(document.frontmatter, DocsFrontmatter)
        and document.frontmatter.docs.project == project
        and document.frontmatter.docs.version == version
    ]


def _dropped_version(collection: Collection, project: str, version: str | None) -> None:
    """Remove a pack's pages of one version of `project`; then the version,
    as `corpus remove --project --version` removes one, when no document is
    left in it. A page of the person's keeps the version."""
    for document in _pages_of(collection, project, version):
        if document.frontmatter.owner != "user":
            _removed(collection, document)
    if version is None:
        return
    if not any(iter_documents(collection.path / project / version)):
        removed_version(collection.path, project, version)


def _removed(collection: Collection, document: Document) -> None:
    """Remove a pack's document, and the groups that leaves empty (Brian,
    2026-10-28). The person's own removals keep their folders for now."""
    folder = holding(document)
    collection.remove(document)
    remove_empty_groups(folder, collection=collection.path)


def _rewrote_bibliography(
    document: Document,
    declaration: Declaration,
    entries: dict[str, Entry],
) -> None:
    """Apply a changed declaration to a paper already held.

    Never the text, and never the identifier. A refetch here would
    delete a document and pull the identical paper down again, which is
    the whole reason the diff is keyed on the identifier.

    **The declaration is authoritative for the citekey and for nothing
    else.** The citekey is the handle the provider's own prose cites, so
    it has to be what the pack says. The title, the authors and the year
    come from the fetch where the fetch has them - arXiv knows the
    paper's own title better than a pack's one-line declaration does -
    and the pack's values fill the gaps.
    """
    entry = entries[declaration.address]
    assert isinstance(entry, LiteratureEntry)
    frontmatter = document.frontmatter
    assert isinstance(frontmatter, LiteratureFrontmatter)
    declared = {entry.paper.kind: entry.paper.value}
    updated = frontmatter.model_copy(
        update={
            "owner": f"pack:{declaration.pack_id}",
            "bib": Bibliography(
                # A citekey neither the pack nor its record gave stays the
                # one the add derived.
                citekey=entry.citekey or frontmatter.bib.citekey,
                authors=frontmatter.bib.authors or entry.author_line,
                year=frontmatter.bib.year or (str(entry.year) if entry.year else None),
                doi=frontmatter.bib.doi or declared.get("doi"),
                arxiv_id=frontmatter.bib.arxiv_id or declared.get("arxiv"),
                bibcode=frontmatter.bib.bibcode or declared.get("bibcode"),
            ),
            "source": frontmatter.source.model_copy(
                update={"pack_sha256": declaration.digest}
            ),
        }
    )
    write_document(document.md_path, frontmatter=updated, body=document.body)


# ---------------------------------------------------------------------------
# The declarations a fetch resolves
# ---------------------------------------------------------------------------


def _literature_plan(corpus_root: Path, packs: tuple[InstalledPack, ...]) -> _Plan:
    """Papers, keyed on the identifier and never on the citekey.

    Section 5 step 3: keying on the citekey would make correcting
    `paperCubicalFast` to `kenyonCubicalFast2018` come out as a removal
    and an addition, deleting a fetched document and pulling the
    identical paper down again.
    """
    declarations, entries = _declared(
        packs,
        listed=lambda pack, files: [
            (literature_key(entry), _literature_digest(entry), entry)
            for entry in pack.corpus.literature
        ],
    )
    collection = Collection(root=corpus_root, name="literature")
    held = _held_papers(collection)
    return _Plan(
        actions=resolve(declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=declarations,
        entries=entries,
        unreadable=_unreadable_in(collection),
    )


def _held_papers(collection: Collection) -> dict[str, tuple[Existing, Document]]:
    """The literature collection's papers, keyed as a declaration is."""
    held: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        frontmatter = document.frontmatter
        if not isinstance(frontmatter, LiteratureFrontmatter):
            continue
        key = bibliography_key(frontmatter.bib)
        if key is None:
            continue
        held[key] = (_declared_existing(key, document), document)
    return held


def _docs_plan(corpus_root: Path, packs: tuple[InstalledPack, ...]) -> _Plan:
    """Documentation, by version of a project: `docs_key`, which is also
    the version's folder (Brian, 2026-10-28). A project declared at two
    versions, by one pack or two, is two declarations; one version two
    packs declare is one, the incumbent's.

    A version is many documents on disk, so `held` keeps one of its pages
    as the representative - written by one crawl, they agree about what was
    declared - and a pack's page before a page of the person's, so a page
    they added into a pack's version does not make the version theirs.
    """
    declarations, entries = _declared(
        packs,
        listed=lambda pack, files: [
            (
                docs_key(entry.project, _declared_version(entry)),
                _docs_digest(entry, files),
                entry,
            )
            for entry in pack.corpus.docs
        ],
    )
    collection = Collection(root=corpus_root, name="docs")
    held: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        frontmatter = document.frontmatter
        if not isinstance(frontmatter, DocsFrontmatter):
            continue
        key = docs_key(frontmatter.docs.project, frontmatter.docs.version)
        incumbent = held.get(key)
        if incumbent is None or (
            incumbent[1].frontmatter.owner == "user" and frontmatter.owner != "user"
        ):
            held[key] = (_declared_existing(key, document), document)
    return _Plan(
        actions=resolve(declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=declarations,
        entries=entries,
        unreadable=_unreadable_in(collection),
    )


def docs_key(project: str, version: str | None) -> str:
    """A docs declaration's address: `<project>/<version>`, its folder; a
    page from before versions (#489) is its project alone."""
    return f"{project}/{version}" if version is not None else project


def _declared_version(entry: DocsEntry) -> str | None:
    """The version a pack's docs entry is filed under: the one it names,
    else the one in its address, which the schema requires one of."""
    if entry.version is not None:
        return entry.version
    return version_in_address(entry.base_url) if entry.base_url else None


def _declared(
    packs: tuple[InstalledPack, ...],
    *,
    listed: Callable[
        [Pack, dict[str, str]], list[tuple[str, str, LiteratureEntry | DocsEntry]]
    ],
) -> tuple[dict[str, Declaration], dict[str, Entry]]:
    """The union of one declaration section, incumbent first.

    The same rule the content union follows: earliest `first_applied_at`
    wins, ties by pack id, and the store path is unused because there is
    nothing in the store to read - a declaration is resolved by fetching.
    """
    ordered = sorted(
        packs, key=lambda one: (one.state.first_applied_at, one.state.pack_id)
    )
    declarations: dict[str, Declaration] = {}
    entries: dict[str, Entry] = {}
    for one in ordered:
        if one.declaration is None:
            continue
        for key, digest, entry in listed(one.declaration, one.state.files):
            if key in declarations:
                continue
            declarations[key] = Declaration(
                address=key,
                pack_id=one.state.pack_id,
                digest=digest,
                store_path=None,
            )
            entries[key] = entry
    return declarations, entries


def _declared_existing(key: str, document: Document) -> Existing:
    """One fetched document, as the resolution table needs to see it.

    `written_digest` is left out, so the `edited` row never fires. That
    is correct rather than a gap: kennis never claims to own a fetched
    paper's prose or a crawled page's, so there is nothing for a user
    edit to be protected from - the only thing a rewrite touches is the
    fields the declaration carries.
    """
    return Existing(
        address=key,
        owner=document.frontmatter.owner,
        body_digest="",
        written_digest=None,
        pack_digest=document.frontmatter.source.pack_sha256,
    )


def literature_key(entry: LiteratureEntry) -> str:
    """`<kind>:<identifier>`, the key a declaration is diffed on."""
    return entry.key


def bibliography_key(bib: Bibliography) -> str | None:
    """The same key, read back off a document kennis wrote.

    None for a paper carrying no identifier at all, which `add_literature`
    refuses to write - so it means a document from some other route, and
    no declaration can be about it.
    """
    if bib.arxiv_id is not None:
        return f"arxiv:{bib.arxiv_id}"
    if bib.doi is not None:
        return f"doi:{bib.doi}"
    if bib.bibcode is not None:
        return f"bibcode:{bib.bibcode}"
    return None


def _literature_digest(entry: LiteratureEntry) -> str:
    """The fields of a paper's declaration, digested.

    Not the paper: there are no bytes until something is fetched, and
    what a sync has to notice is the *declaration* moving. A changed
    citekey or a corrected title moves this; the identifier cannot,
    because it is the key.
    """
    return content_digest(
        "\n".join(
            [
                entry.citekey or "",
                entry.title or "",
                entry.author_line or "",
                str(entry.year or ""),
                # Where the text is fetched from is part of what was
                # declared: a corrected address is a declaration that moved.
                entry.url or "",
                entry.file or "",
            ]
        ).encode("utf-8")
    )


def _link_digest(note: NoteLink) -> str:
    """The fields of a note declared by address, digested: a corrected
    title or group is a declaration that moved, and is fetched again."""
    return content_digest(
        "\n".join([note.url, note.title or "", note.group or ""]).encode("utf-8")
    )


def _docs_digest(entry: DocsEntry, files: dict[str, str]) -> str:
    """The fields of a documentation project's declaration, digested.

    For local pages, each page's path and checksum in the store as well, so
    a changed page is a project that moved and is added again.
    """
    # The version only when given, so a declaration written before it
    # existed keeps its digest and is not crawled again for nothing.
    fields = [entry.project, entry.base_url or "", *sorted(entry.exclude)]
    if entry.version is not None:
        fields.append(f"version={entry.version}")
    fields.extend(f"{page}={files.get(page, '')}" for page in entry.pages)
    return content_digest("\n".join(fields).encode("utf-8"))


def _file_digest(note: NoteFile, files: dict[str, str]) -> str:
    """A shipped note's checksum in the store, with its declared title and
    group: a changed file, title or group is a declaration that moved."""
    return content_digest(
        "\n".join(
            [files.get(note.file, ""), note.title or "", note.group or ""]
        ).encode("utf-8")
    )


def _held(collection: Collection) -> dict[str, tuple[Existing, Document]]:
    """Every note a pack supplied, keyed by the address it was declared at.

    Read from `source.from` rather than from the path, because the path
    follows the title. A document the user wrote is not here at all: it
    sits at no pack's address, so it is not a sync's business - not even
    to report.
    """
    found: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        source = document.frontmatter.source
        if source.via != "pack" or not source.origin.startswith(ORIGIN_SCHEME):
            continue
        address = source.origin[len(ORIGIN_SCHEME) :].split("/", 1)[-1]
        found[address] = (
            Existing(
                address=address,
                owner=document.frontmatter.owner,
                body_digest=content_digest(document.body.encode("utf-8")),
                written_digest=source.sha256,
                pack_digest=source.pack_sha256,
            ),
            document,
        )
    return found


def _applied(
    collection: Collection,
    record: Uniqueness,
    action: Action,
    plan: _Plan,
    client: httpx.Client | None,
) -> None:
    """Carry out one action. `keep` and `yours` write nothing; `edited` is
    `_kept_as_theirs`'s."""
    if action.verdict == "delete":
        _removed(collection, plan.held[action.address][1])
        return
    if action.verdict not in {"write", "rewrite", "adopt"}:
        return
    declaration = action.declaration
    assert declaration is not None
    content = _content_of(declaration, plan.entries.get(action.address), client)
    group = _declared_group(plan, declaration)
    if action.verdict == "write":
        _written(collection, record, declaration, content, group=group)
        return
    _rewritten(plan.held[action.address][1], declaration, content)


def _kept_as_theirs(
    collection: Collection,
    record: Uniqueness,
    action: Action,
    plan: _Plan,
    client: httpx.Client | None,
) -> tuple[str, str]:
    """A pack note the person edited: the edit becomes a note of theirs,
    then the original is the pack's again - rewritten from what the pack
    declares, or removed when it declares it no longer (#514). The copy
    first, so an interrupt between the two loses nothing."""
    held = plan.held[action.address][1]
    mine = copied_note(collection, record, held)
    declaration = action.declaration
    if declaration is None:
        _removed(collection, held)
    else:
        content = _content_of(declaration, plan.entries.get(action.address), client)
        _rewritten(held, declaration, content)
    return held.id, mine.id


@dataclass(frozen=True, slots=True)
class _NoteContent:
    title: str
    body: str
    format: SourceFormat


# A shipped file read as it is, frontmatter and all. Anything else a pack
# ships is converted, as `corpus add -n` would convert it.
_MARKDOWN_SUFFIXES: Final = frozenset({".md", ".markdown"})


def _content_of(
    declaration: Declaration, entry: Entry | None, client: httpx.Client | None
) -> _NoteContent:
    """The title, body and format for one declared note.

    A shipped markdown file is read as it is. When it carries its own
    frontmatter that block supplies the title and the rest is the body -
    never nested, never two blocks in one document. Otherwise the title
    comes from the prose the way `remember` derives one, so a pack note
    and a remembered one are named by the same rule.

    A note declared by address is fetched, and a shipped file of another
    kind converted, by the functions `corpus add -n` uses, and named in
    `add_notes`'s order: the declared title, the source's own name, the
    title the source suggests (#459).
    """
    if isinstance(entry, NoteLink):
        converted = convert_url(entry.url, client=client)
        return _NoteContent(
            title=entry.title
            or converted.source_name
            or converted.suggested_title
            or entry.url,
            body=converted.markdown,
            format=converted.format,
        )
    # A content declaration always has one; only a paper, a documentation
    # project or a note declared by address, which a fetch resolves, does not.
    assert declaration.store_path is not None
    named = entry.title if isinstance(entry, NoteFile) else None
    if declaration.store_path.suffix.lower() not in _MARKDOWN_SUFFIXES:
        converted = convert_local_file(declaration.store_path)
        return _NoteContent(
            title=named
            or converted.source_name
            or converted.suggested_title
            or title_for(converted.markdown),
            body=converted.markdown,
            format=converted.format,
        )
    content = declaration.store_path.read_text(encoding="utf-8")
    shipped, body = split_frontmatter(content)
    declared_title = shipped.get("title")
    title = named or (str(declared_title) if declared_title else title_for(body))
    return _NoteContent(title=title, body=body, format="markdown")


def _written(
    collection: Collection,
    record: Uniqueness,
    declaration: Declaration,
    content: _NoteContent,
    *,
    group: str,
) -> None:
    """A note this corpus has not held before, with a minted identifier.

    **Deliberately not deduplicated against the user's notes.** A pack
    shipping prose somebody already remembered is a different document
    with a different owner, and folding the two together would hand a
    user's note to a pack - or leave the pack's declaration pointing at a
    document the pack does not own. `remember`'s deduplication exists to
    stop an agent saying the same thing twice; two sources saying it once
    each is not that.
    """
    write_note(
        collection,
        record,
        converted=Converted(
            markdown=content.body,
            via="pack",
            format=content.format,
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            sha256=content_digest(content.body.encode("utf-8")),
        ),
        title=content.title,
        group=group,
        owner=f"pack:{declaration.pack_id}",
        pack_sha256=declaration.digest,
    )


def _note_group(declaration: Declaration) -> str:
    """Where a pack's note is filed: under the pack, in its address's folders."""
    inside = declaration.address.rpartition("/")[0]
    return "/".join(part for part in (declaration.pack_id, inside) if part)


def _rewritten(
    document: Document, declaration: Declaration, content: _NoteContent
) -> None:
    """A note this corpus already holds, kept at its own identifier.

    The file is rewritten where it stands. Its filename came from the
    title it had when it was first written and is left alone even when
    the title moves: renaming is `corpus move`'s job, it is not what a
    sync was asked to do, and the filename is not the identity.
    """
    frontmatter = NoteFrontmatter(
        id=document.id,
        title=content.title,
        owner=f"pack:{declaration.pack_id}",
        source=Source(
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            via="pack",
            format=content.format,
            sha256=content_digest(content.body.encode("utf-8")),
            pack_sha256=declaration.digest,
        ),
        id_from=document.frontmatter.id_from,
    )
    write_document(document.md_path, frontmatter=frontmatter, body=content.body)


def _reported(
    events: EventSink | None,
    actions: tuple[Action, ...],
    places: dict[str, str],
    started: float,
) -> None:
    if events is None:
        return
    counts: Counter[Outcome] = Counter()
    for action in actions:
        outcome = _OUTCOMES[action.verdict]
        counts[outcome] += 1
        events.emit(
            ItemFinished(
                operation=OPERATION,
                item=places.get(action.address, action.address),
                outcome=outcome,
                refusal=Quoted(action.verdict),
            )
        )
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts=dict(counts),
        )
    )


__all__ = [
    "OPERATION",
    "ORIGIN_SCHEME",
    "CorpusSync",
    "supply_paper",
    "sync_corpus",
]
