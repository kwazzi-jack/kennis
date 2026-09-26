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
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from kennis.engine.corpus.add import (
    AddOptions,
    Uniqueness,
    add_docs,
    add_literature,
    write_note,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, write_document
from kennis.engine.corpus.intake import Converted
from kennis.engine.corpus.schema import (
    Bibliography,
    DocsFrontmatter,
    LiteratureFrontmatter,
    NoteFrontmatter,
    Source,
)
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import (
    InstalledPack,
    declared_content,
    list_installed,
    refuse_damaged_packs,
)
from kennis.engine.pack.resolve import Action, Declaration, Existing, Verdict, resolve
from kennis.engine.pack.schema import DocsEntry, LiteratureEntry, Pack
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
    "edited": Outcome.SKIPPED,
    "yours": Outcome.SKIPPED,
}


@dataclass(frozen=True, slots=True)
class CorpusSync:
    """What one `corpus sync` did, by verdict.

    `edited` carries the surrogate identifier of each document kennis
    declined to rewrite, which the bundle's equivalent has no use for: a
    corpus document is addressed by that identifier and `corpus claim`
    is the only handle on it, so the report cannot name the command to
    run without it. Section 5 step 4a names that command for exactly
    this case.
    """

    actions: tuple[Action, ...]
    counts: dict[Verdict, int]
    deferred: tuple[tuple[str, str], ...]
    edited: tuple[str, ...]
    # Declarations whose fetch did not succeed. Not a verdict: the
    # declaration still stands and the document is still absent, so the
    # next run tries again. One unreachable host must not stop the other
    # nine papers from arriving.
    failed: tuple[str, ...] = ()


def sync_corpus(
    corpus_root: Path,
    *,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    client: httpx.Client | None = None,
    request_delay_seconds: float | None = None,
) -> CorpusSync:
    """Converge the corpus with every installed pack.

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
    packs = list_installed(corpus_root).packs
    refuse_damaged_packs(packs)

    notes = _notes_plan(corpus_root, packs)
    papers = _literature_plan(corpus_root, packs)
    projects = _docs_plan(corpus_root, packs)
    _refuse_what_cannot_be_classified(notes, papers, projects)

    failed = _carried_out(
        corpus_root,
        notes,
        papers,
        projects,
        arxiv=arxiv,
        client=client,
        request_delay_seconds=request_delay_seconds,
        events=events,
    )

    actions = notes.actions + papers.actions + projects.actions
    counts = Counter(action.verdict for action in actions)
    _reported(events, actions, started)
    return CorpusSync(
        actions=actions,
        counts=dict(counts),
        deferred=notes.deferred,
        edited=tuple(
            notes.held[action.address][1].id
            for action in notes.actions
            if action.verdict == "edited"
        ),
        failed=failed,
    )


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
    # neither. Empty for notes, whose content is in the store.
    entries: dict[str, LiteratureEntry | DocsEntry] = field(default_factory=dict)
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


def _unreadable_in(collection: Collection) -> tuple[str, ...]:
    """The names of documents in this collection that will not validate."""
    return tuple(
        sorted(facts.md_path.name for facts in collection.contents().unreadable)
    )


def _notes_plan(corpus_root: Path, packs: tuple[InstalledPack, ...]) -> _Plan:
    union = declared_content(corpus_root, packs, "notes")
    collection = Collection(root=corpus_root, name="notes")
    held = _held(collection)
    return _Plan(
        actions=resolve(union.declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=union.declarations,
        unreadable=_unreadable_in(collection),
        deferred=union.deferred,
    )


def _carried_out(
    corpus_root: Path,
    notes: _Plan,
    papers: _Plan,
    projects: _Plan,
    *,
    arxiv: httpx.Client | None,
    client: httpx.Client | None,
    request_delay_seconds: float | None,
    events: EventSink | None,
) -> tuple[str, ...]:
    """Do what the three plans decided, and report what would not happen.

    Notes first, because they are the part that cannot fail: copying out
    of a verified store either works or the store was damaged, and that
    was refused before this was called. The two that reach a host go
    afterwards, so an unreachable one leaves a corpus that is otherwise
    converged.
    """
    collection = Collection(root=corpus_root, name="notes")
    record = Uniqueness.of(collection)
    for action in notes.actions:
        _applied(collection, record, action, notes.held)

    failed = list(
        _fetched_literature(
            corpus_root,
            papers,
            arxiv=arxiv,
            request_delay_seconds=request_delay_seconds,
            events=events,
        )
    )
    failed.extend(
        _crawled_docs(
            corpus_root,
            projects,
            client=client,
            request_delay_seconds=request_delay_seconds,
            events=events,
        )
    )
    return tuple(failed)


def _fetched_literature(
    corpus_root: Path,
    plan: _Plan,
    *,
    arxiv: httpx.Client | None,
    request_delay_seconds: float | None,
    events: EventSink | None,
) -> list[str]:
    """Fetch the papers that are missing, rewrite the ones that moved.

    A `rewrite` never refetches. Section 5 step 3 makes a changed
    citekey against an unchanged identifier a rename, so the bib fields
    are replaced in place and the document, its identifier and its text
    are left alone.
    """
    collection = Collection(root=corpus_root, name="literature")
    failed: list[str] = []
    for action in plan.actions:
        declaration = action.declaration
        if action.verdict == "delete":
            collection.remove(plan.held[action.address][1])
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
        report = add_literature(
            collection,
            [action.address],
            AddOptions(
                # The pack's citekey, not a derived one. It is the handle
                # the provider's own prose cites, so a document that
                # arrived under a citekey kennis invented would answer to
                # nothing the pack says.
                citekey=entry.citekey,
                owner=f"pack:{declaration.pack_id}",
                pack_sha256=declaration.digest,
                request_delay_seconds=request_delay_seconds,
            ),
            arxiv=arxiv,
            events=events,
        )
        if not any(one.outcome is Outcome.ADDED for one in report.outcomes):
            failed.append(action.address)
    return failed


def _crawled_docs(
    corpus_root: Path,
    plan: _Plan,
    *,
    client: httpx.Client | None,
    request_delay_seconds: float | None,
    events: EventSink | None,
) -> list[str]:
    """Crawl the projects that are missing, drop the ones that went.

    **`keep` does not re-crawl.** A crawl is hundreds of requests, the
    design's diff key for docs is the project alone, and refreshing a
    site is what `corpus add --docs` is for. Concern #277.

    A delete removes every page of the project, because the unit of
    declaration is the project and leaving some pages would leave a
    project nothing declares and nothing would ever clean it.
    """
    collection = Collection(root=corpus_root, name="docs")
    failed: list[str] = []
    for action in plan.actions:
        declaration = action.declaration
        if action.verdict == "delete":
            _removed_project(collection, action.address)
            continue
        if action.verdict not in {"write", "rewrite", "adopt"}:
            continue
        if declaration is None:
            continue
        entry = plan.entries[action.address]
        assert isinstance(entry, DocsEntry)
        report = add_docs(
            collection,
            [entry.base_url],
            AddOptions(
                project=entry.project,
                exclude=tuple(entry.exclude),
                owner=f"pack:{declaration.pack_id}",
                pack_sha256=declaration.digest,
                request_delay_seconds=request_delay_seconds,
            ),
            client=client,
            events=events,
        )
        if not any(one.outcome is Outcome.ADDED for one in report.outcomes):
            failed.append(action.address)
    return failed


def _removed_project(collection: Collection, project: str) -> None:
    for document in list(collection.contents().documents):
        frontmatter = document.frontmatter
        if (
            isinstance(frontmatter, DocsFrontmatter)
            and frontmatter.docs.project == project
        ):
            collection.remove(document)


def _rewrote_bibliography(
    document: Document,
    declaration: Declaration,
    entries: dict[str, LiteratureEntry | DocsEntry],
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
    updated = frontmatter.model_copy(
        update={
            "owner": f"pack:{declaration.pack_id}",
            "bib": Bibliography(
                citekey=entry.citekey,
                authors=frontmatter.bib.authors or entry.authors,
                year=frontmatter.bib.year or (str(entry.year) if entry.year else None),
                doi=frontmatter.bib.doi or entry.doi,
                arxiv_id=frontmatter.bib.arxiv_id or entry.arxiv_id,
                bibcode=frontmatter.bib.bibcode or entry.bibcode,
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
        listed=lambda pack: [
            (literature_key(entry), _literature_digest(entry), entry)
            for entry in pack.corpus.literature
        ],
    )
    collection = Collection(root=corpus_root, name="literature")
    held: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        frontmatter = document.frontmatter
        if not isinstance(frontmatter, LiteratureFrontmatter):
            continue
        key = bibliography_key(frontmatter.bib)
        if key is None:
            continue
        held[key] = (_declared_existing(key, document), document)
    return _Plan(
        actions=resolve(declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=declarations,
        entries=entries,
        unreadable=_unreadable_in(collection),
    )


def _docs_plan(corpus_root: Path, packs: tuple[InstalledPack, ...]) -> _Plan:
    """Documentation projects. The unit of declaration is the project.

    A project is many documents on disk, so `held` keeps one of its
    pages as the representative - they were written by one crawl and
    agree about what was declared - and a delete removes all of them.
    """
    declarations, entries = _declared(
        packs,
        listed=lambda pack: [
            (entry.project, _docs_digest(entry), entry) for entry in pack.corpus.docs
        ],
    )
    collection = Collection(root=corpus_root, name="docs")
    held: dict[str, tuple[Existing, Document]] = {}
    for document in collection.contents().documents:
        frontmatter = document.frontmatter
        if not isinstance(frontmatter, DocsFrontmatter):
            continue
        project = frontmatter.docs.project
        if project not in held:
            held[project] = (_declared_existing(project, document), document)
    return _Plan(
        actions=resolve(declarations, {one: held[one][0] for one in held}),
        held=held,
        declarations=declarations,
        entries=entries,
        unreadable=_unreadable_in(collection),
    )


def _declared(
    packs: tuple[InstalledPack, ...],
    *,
    listed: Callable[[Pack], list[tuple[str, str, LiteratureEntry | DocsEntry]]],
) -> tuple[dict[str, Declaration], dict[str, LiteratureEntry | DocsEntry]]:
    """The union of one declaration section, incumbent first.

    The same rule the content union follows: earliest `first_applied_at`
    wins, ties by pack id, and the store path is unused because there is
    nothing in the store to read - a declaration is resolved by fetching.
    """
    ordered = sorted(
        packs, key=lambda one: (one.state.first_applied_at, one.state.pack_id)
    )
    declarations: dict[str, Declaration] = {}
    entries: dict[str, LiteratureEntry | DocsEntry] = {}
    for one in ordered:
        if one.declaration is None:
            continue
        for key, digest, entry in listed(one.declaration):
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
    """`arxiv:`, else `doi:`, else `bibcode:`, with the scheme in the key.

    The scheme is part of it so a DOI and an arXiv id that happen to
    share a string cannot collide.
    """
    if entry.arxiv_id is not None:
        return f"arxiv:{entry.arxiv_id}"
    if entry.doi is not None:
        return f"doi:{entry.doi}"
    return f"bibcode:{entry.bibcode}"


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
                entry.citekey,
                entry.title,
                entry.authors or "",
                str(entry.year or ""),
                entry.doi or "",
                entry.bibcode or "",
            ]
        ).encode("utf-8")
    )


def _docs_digest(entry: DocsEntry) -> str:
    """The fields of a documentation project's declaration, digested."""
    return content_digest(
        "\n".join([entry.project, entry.base_url, *sorted(entry.exclude)]).encode(
            "utf-8"
        )
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
    held: dict[str, tuple[Existing, Document]],
) -> None:
    """Carry out one action. `keep`, `yours` and `edited` write nothing."""
    if action.verdict == "delete":
        collection.remove(held[action.address][1])
        return
    if action.verdict not in {"write", "rewrite", "adopt"}:
        return
    declaration = action.declaration
    assert declaration is not None
    title, body = _content_of(declaration)
    if action.verdict == "write":
        _written(collection, record, declaration, title=title, body=body)
        return
    _rewritten(held[action.address][1], declaration, title=title, body=body)


def _content_of(declaration: Declaration) -> tuple[str, str]:
    """The title and body for one declared note.

    A pack ships plain markdown. When its file carries its own
    frontmatter that block supplies the title and the rest is the body -
    never nested, never two blocks in one document. Otherwise the title
    comes from the prose the way `remember` derives one, so a pack note
    and a remembered one are named by the same rule.
    """
    # A content declaration always has one; only a paper or a
    # documentation project, which a fetch resolves, does not.
    assert declaration.store_path is not None
    content = declaration.store_path.read_text(encoding="utf-8")
    shipped, body = split_frontmatter(content)
    declared_title = shipped.get("title")
    title = str(declared_title) if declared_title else title_for(body)
    return title, body


def _written(
    collection: Collection,
    record: Uniqueness,
    declaration: Declaration,
    *,
    title: str,
    body: str,
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
            markdown=body,
            via="pack",
            format="markdown",
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            sha256=content_digest(body.encode("utf-8")),
        ),
        title=title,
        group=None,
        owner=f"pack:{declaration.pack_id}",
        pack_sha256=declaration.digest,
    )


def _rewritten(
    document: Document, declaration: Declaration, *, title: str, body: str
) -> None:
    """A note this corpus already holds, kept at its own identifier.

    The file is rewritten where it stands. Its filename came from the
    title it had when it was first written and is left alone even when
    the title moves: renaming is `corpus move`'s job, it is not what a
    sync was asked to do, and the filename is not the identity.
    """
    frontmatter = NoteFrontmatter(
        id=document.id,
        title=title,
        owner=f"pack:{declaration.pack_id}",
        source=Source(
            origin=f"{ORIGIN_SCHEME}{declaration.pack_id}/{declaration.address}",
            via="pack",
            format="markdown",
            sha256=content_digest(body.encode("utf-8")),
            pack_sha256=declaration.digest,
        ),
        id_from=document.frontmatter.id_from,
    )
    write_document(document.md_path, frontmatter=frontmatter, body=body)


def claim_document(corpus_root: Path, handle: str) -> Document:
    """Move a document from its pack to the user. Design section 6.

    **`source` is left alone**, which is what keeps the document at its
    address: the next sync still finds it, sees `owner: user`, and
    reports it under `yours:` rather than rewriting it. A claim that
    erased the origin would make the next sync write a second copy of the
    same note.

    Claiming a document the user already owns is harmless and does
    nothing, because the end state is what was asked for.
    """
    collection = Collection(root=corpus_root, name="notes")
    document = collection.resolve(handle)
    if document.frontmatter.owner == "user":
        return document
    return _reowned(document, "user")


def disown_document(corpus_root: Path, handle: str) -> Document:
    """Hand a document back to the pack it came from. Design section 6.

    Only a document that came from one: the pack is read back out of
    `source.from`, and there is nothing to read for a note the user
    wrote. Inventing a pack would be a claim about provenance that is not
    true, and the next sync would then delete the document, because no
    pack declares it.
    """
    collection = Collection(root=corpus_root, name="notes")
    document = collection.resolve(handle)
    source = document.frontmatter.source
    if source.via != "pack" or not source.origin.startswith(ORIGIN_SCHEME):
        raise DocumentInvalid(
            f"'{handle}' did not come from a pack, so there is none to hand it back to",
            resolution="kennis corpus list",
        )
    pack_id = source.origin[len(ORIGIN_SCHEME) :].split("/", 1)[0]
    return _reowned(document, f"pack:{pack_id}")


def _reowned(document: Document, owner: str) -> Document:
    """Rewrite one document with a new `owner` and nothing else changed."""
    frontmatter = document.frontmatter.model_copy(update={"owner": owner})
    return write_document(document.md_path, frontmatter=frontmatter, body=document.body)


def _reported(
    events: EventSink | None, actions: tuple[Action, ...], started: float
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
                item=action.address,
                outcome=outcome,
                reason=action.verdict,
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
    "claim_document",
    "disown_document",
    "sync_corpus",
]
