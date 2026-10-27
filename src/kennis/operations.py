"""The mutating operations, as a sequence every front end can share.

The fifth module beside `context.py`, and there for the reason the
other four are: **restore hand deletions, prepare, publish** is one
sequence performed identically by whoever asks, and `gui/` may not import
`cli/` to get it.

**Prepare, then publish** (14e, #507). An operation runs against a mirror
of the collections holding no lock (`engine/staging.py`), and is then
published - placed and committed - while the corpus is held exclusively
(`publishing.py`), so a read sees it wholly or not at all and an
interruption while preparing changes nothing. A restore and a return are
written by git into the working tree and are quick, so they run held
throughout, inside a journal that puts them back if they fail.

`writing.py` did this for one note. This does it for the rest of corpus
management - adding, indexing, both syncs and installing a pack -
because unit 9f needs every one of them from a second front end and
copying the sequence is how the two front ends drift apart.

**What is not here is wording**, as in `writing.py`. Every function
returns the engine's own report and `_undo_hand_deletions` became
`restore_hand_deletions`, which *returns* what it restored instead of
printing it. Concern #324.

**Three disciplines, and the differences are not accidents.**

- The corpus is kennis's own git repository, so an operation that
  writes into it publishes and commits.
- `install_a_pack` locks, because the store lives under the corpus
  root and a sync reads it, and does not commit, because the store is
  not the corpus's tracked content.
- `synchronise_bundle` does neither: a bundle lives inside a
  repository kennis does not own, and committing there would take over
  the user's version control.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from kennis.context import Context
from kennis.engine.atomic import remove_file, remove_tree
from kennis.engine.backup import BackupReport, write_backup
from kennis.engine.context.bundle import declare_packs, declared_packs, index_root_for
from kennis.engine.context.index import index_bundle
from kennis.engine.context.reset import removable_documents
from kennis.engine.context.sync import BundleSync, sync_bundle
from kennis.engine.corpus.add import (
    AddOptions,
    AddReport,
    Uniqueness,
    add_docs,
    add_literature,
    add_notes,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.copying import copied_note
from kennis.engine.corpus.document import Document, move_document, seal_if_obtained
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.moving import move_target, refuse_regrouping_docs
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import (
    CorpusSync,
    supply_paper,
    sync_corpus,
)
from kennis.engine.docs.versions import (
    current_version_file,
    make_current,
    pages_of_version,
    project_versions,
)
from kennis.engine.errors import IndexBusy
from kennis.engine.events import Event, EventSink, Outcome
from kennis.engine.history.history import (
    RestoredDocument,
    ReturnChanges,
    commit_summary,
    document_path_at,
    outcome_summary,
    restore_document,
    return_to,
    what_a_return_changes,
)
from kennis.engine.history.outofband import (
    OutOfBandChange,
    detect_changes,
    restore_deletions,
)
from kennis.engine.history.repository import Repository
from kennis.engine.pack.installed import PackRemoval, uninstall_pack
from kennis.engine.pack.store import PackInstall, install_pack
from kennis.engine.rag.binding import binding_from, chunk_parameters
from kennis.engine.rag.embedding import ModelBinding
from kennis.engine.rag.index import BuildReport, build_index
from kennis.engine.rag.loaders import CollectionLoader
from kennis.engine.staging import (
    RECORD_SUMMARY,
    Mirror,
    discard,
    journalled,
    make_mirror,
    publish,
)
from kennis.finding import resolve_document
from kennis.publishing import exclusively, shared
from kennis.render.packs import describe_sync_summary

_ADDERS = {"notes": add_notes, "literature": add_literature, "docs": add_docs}


class _Rebasing:
    """An `EventSink` that names the corpus where an event names the
    mirror an operation is preparing in."""

    def __init__(self, sink: EventSink, mirror: Mirror) -> None:
        self._sink = sink
        self._mirror = mirror

    def emit(self, event: Event) -> None:
        self._sink.emit(self._mirror.rebased(event))


def _prepared_then_published[Result](
    context: Context,
    prepare: Callable[[Context, EventSink | None], Result],
    *,
    operation: str,
    scope: str,
    summary: Callable[[Result], str],
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> Result:
    """Restore, prepare in a mirror, publish: the sequence every write to
    the collections shares.

    The hand deletions are put back and the mirror made in one exclusive
    hold, so the mirror is the corpus as restored and never half of
    another publish. `prepare` is given a context whose corpus is the
    mirror, and what it returns, emits or raises names the corpus again
    before anyone sees it. Nothing is placed unless `prepare` returns.
    """
    root = context.corpus_root
    with exclusively(root):
        put_back = restore_hand_deletions(context)
        mirror = make_mirror(root)
    if restored is not None:
        restored.extend(put_back)
    try:
        staged = replace(context, corpus_root=mirror.root)
        sink = _Rebasing(events, mirror) if events is not None else None
        try:
            result = mirror.rebased(prepare(staged, sink))
        except BaseException as error:
            mirror.rebase_error(error)
            raise
        with exclusively(root):
            publish(mirror, operation=operation, scope=scope, summary=summary(result))
    finally:
        discard(mirror)
    return result


@dataclass(frozen=True, slots=True)
class BuiltIndex:
    """One collection's index, and what went into it."""

    collection: str
    documents: int
    chunks: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class IndexBuild:
    """What one `index` invocation built, per collection and in total.

    The model's kind and name are two fields kennis is quoting; a front
    end that wants to say "using ..." has both, and one that wants to
    say nothing ignores them. Both are None for a lexical-only
    binding, which is a different sentence rather than an empty one.

    `busy` names the collections another process was already
    rebuilding. Recorded rather than raised, so that one contended
    index does not abandon the two that were free - and so that what
    *was* built is still committed. Concern #167.
    """

    built: list[BuiltIndex]
    busy: tuple[str, ...] = ()
    model_kind: str | None = None
    model_name: str | None = None

    @property
    def documents(self) -> int:
        return sum(index.documents for index in self.built)

    @property
    def chunks(self) -> int:
        return sum(index.chunks for index in self.built)


def restore_hand_deletions(context: Context) -> list[OutOfBandChange]:
    """Put back anything deleted outside kennis, and say what was put back.

    design.md, "Changes made outside kennis": **a deletion is restored
    rather than honoured**. An out-of-band delete carries no record of
    intent, and treating an accident as an instruction is the more
    expensive mistake - restoring costs an annoying extra command,
    honouring costs a document.

    **Called inside the lock and before the operation**, so that the
    command's own commit carries a tree the deletion never touched.
    Without it the deletion is not merely unnoticed: the next commit
    stages it, and the accident becomes history. Concern #128.
    """
    repository = Repository(context.corpus_root)
    restored = [
        change
        for change in restore_deletions(repository, detect_changes(repository))
        if change.restored
    ]
    sealed_again(context, [change.path for change in restored])
    return restored


def record_what_was_not_recorded(context: Context) -> str | None:
    """Commit what is in the corpus and not yet in history, as
    `record(corpus)`, and return the commit - None when there was nothing.

    Called held, before a write git makes itself commits - a restore, a
    return (#525 item 3, Brian, 2026-10-21): every commit stages with
    `git add --all .`, so an edit made by hand would otherwise enter
    history under the name of whatever kennis wrote next. A publish does
    the same in `staging.publish`, only when it has something to place.
    """
    return Repository(context.corpus_root).commit(
        "record", scope="corpus", summary=RECORD_SUMMARY
    )


def sealed_again(context: Context, paths: Sequence[str]) -> None:
    """Make what git just wrote read-only again where kennis obtained it
    (14g, #514). `paths` are relative to the corpus root."""
    for relative in paths:
        collection = relative.split("/", 1)[0]
        path = context.corpus_root / relative
        if collection in COLLECTION_NAMES and path.suffix == ".md" and path.is_file():
            seal_if_obtained(path, collection=collection)


def add_documents(
    context: Context,
    destination: str,
    identifiers: Sequence[str],
    options: AddOptions,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> AddReport:
    """Add to one collection: restore, add in a mirror, publish.

    `restored` is filled in place rather than returned beside the
    report, because a caller that wants both wants them in the order
    they happened and a tuple return would read as though the restore
    were part of the add. Passing None asks for the restore without
    hearing about it, which is what a caller with nowhere to print it
    means.
    """

    def added(staged: Context, sink: EventSink | None) -> AddReport:
        target = Collection(root=staged.corpus_root, name=destination)
        return _ADDERS[destination](target, identifiers, options, events=sink)

    return _prepared_then_published(
        context,
        added,
        operation="add",
        scope=destination,
        summary=lambda report: outcome_summary(report.counts),
        events=events,
        restored=restored,
    )


@dataclass(frozen=True, slots=True)
class GroupBlock:
    """One group of the window's Several by group tab: where, under what
    name, and what to add."""

    collection: str
    group: str
    identifiers: tuple[str, ...]


def add_in_groups(
    context: Context,
    blocks: Sequence[GroupBlock],
    options: AddOptions,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> AddReport:
    """Several adds as one job, one per group, merged into one report.

    **Each block is its own add** - its own lock, restore and commit -
    because a block can name a different collection and `add_documents`
    commits per collection. One report, because the window shows one
    job; each outcome names its own input, which is what says which
    block it came from.
    """
    reports = [
        add_documents(
            context,
            block.collection,
            block.identifiers,
            replace(options, group=block.group),
            events=events,
            restored=restored,
        )
        for block in blocks
    ]
    costs = [report.cost_cents for report in reports if report.cost_cents is not None]
    return AddReport(
        outcomes=[outcome for report in reports for outcome in report.outcomes],
        elapsed_seconds=sum(report.elapsed_seconds for report in reports),
        cost_cents=sum(costs) if costs else None,
        repairs=sum(report.repairs for report in reports),
    )


def move_a_document(
    context: Context,
    collection: Collection,
    document: Document,
    *,
    group: str | None,
    title: str | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> Document:
    """Refile or rename one document: restore, move in a mirror, publish.

    The sequence `corpus move` ran inside the command line, here so the
    window's tree runs the same one. A docs page is refused a group
    before the lock is taken (#101). `restored` is filled in place, as
    `add_documents` fills it, for a caller that says what came back.
    """
    refuse_regrouping_docs(collection, group)

    def moved(staged: Context, sink: EventSink | None) -> Document:
        held = Collection(root=staged.corpus_root, name=collection.name)
        mirrored = held.resolve(document.id)
        return move_document(
            mirrored,
            target_md_path=move_target(held, mirrored, group=group, title=title),
            updates={"title": title} if title else None,
        )

    return _prepared_then_published(
        context,
        moved,
        operation="move",
        scope=collection.name,
        summary=lambda _: outcome_summary({Outcome.CHANGED: 1}),
        restored=restored,
    )


def copy_a_document(
    context: Context,
    handle: str,
    collection: str | None = None,
    *,
    restored: list[OutOfBandChange] | None = None,
) -> Document:
    """A new note of the person's from any document: restore, copy in a
    mirror, publish (14g, #514). The original is not touched."""
    copied_from: list[str] = []

    def copied(staged: Context, sink: EventSink | None) -> Document:
        _, original = resolve_document(staged, handle, collection)
        copied_from.append(original.id)
        notes = Collection(root=staged.corpus_root, name="notes")
        return copied_note(notes, Uniqueness.of(notes), original)

    return _prepared_then_published(
        context,
        copied,
        operation="copy",
        scope="notes",
        summary=lambda copy: f"{copied_from[0]} as {copy.id}",
        restored=restored,
    )


def make_docs_version_current(context: Context, project: str, version: str) -> None:
    """Search `version` of `project` by default: restore, write in a
    mirror, publish.

    Through the lock and into history like any other write to the corpus,
    because `.current` is a file of it: uncommitted, the next write would
    sweep it in under another operation's name (#489).
    """
    pages_of_version(
        Collection(root=context.corpus_root, name="docs").path, project, version
    )

    def made_current(staged: Context, sink: EventSink | None) -> None:
        docs = Collection(root=staged.corpus_root, name="docs")
        make_current(docs.path, project, version)

    _prepared_then_published(
        context,
        made_current,
        operation="version",
        scope="docs",
        summary=lambda _: f"{project} {version}",
    )


@dataclass(frozen=True, slots=True)
class RemovedVersion:
    """What removing one version of a docs project did."""

    project: str
    version: str
    pages: int
    # The project's current version afterwards; None when none is left.
    current: str | None


def remove_docs_version(context: Context, project: str, version: str) -> RemovedVersion:
    """Remove every page of one version of a docs project, as one write:
    restore, remove in a mirror, publish (#489).

    The folder goes whole, so a page kennis cannot read goes with the rest
    rather than keeping a version alive that the reader removed. A record
    of the current version that named it goes too, so the newest version
    left is current; one naming another version stays. A project left with
    no version is removed. Recoverable through git like any removal.
    """

    def removed(staged: Context, sink: EventSink | None) -> RemovedVersion:
        docs = Collection(root=staged.corpus_root, name="docs")
        project_dir = docs.path / project
        # Counted in the mirror, which nothing else writes to.
        pages = pages_of_version(docs.path, project, version)
        remove_tree(project_dir / version)
        record = current_version_file(docs.path, project)
        if record.is_file() and record.read_text(encoding="utf-8").strip() == version:
            remove_file(record)
        left = project_versions(docs.path).get(project)
        if left is None:
            remove_tree(project_dir)
        return RemovedVersion(
            project=project,
            version=version,
            pages=pages,
            current=left.current if left is not None else None,
        )

    return _prepared_then_published(
        context,
        removed,
        operation="remove",
        scope="docs",
        summary=lambda done: (
            f"{project} {version}, " + outcome_summary({Outcome.REMOVED: done.pages})
        ),
    )


def remove_a_document(
    context: Context, collection: Collection, document: Document
) -> Document:
    """Remove one document, and its assets when it has any: restore, remove
    in a mirror, publish.

    The sequence `corpus remove` ran inside the command line, here so the
    window runs the same one. Recoverable: the removal is a commit, and
    `restore_a_document` puts it back from the commit before it.
    """

    def removed(staged: Context, sink: EventSink | None) -> None:
        held = Collection(root=staged.corpus_root, name=collection.name)
        held.remove(held.resolve(document.id))

    _prepared_then_published(
        context,
        removed,
        operation="remove",
        scope=collection.name,
        summary=lambda _: outcome_summary({Outcome.REMOVED: 1}),
    )
    return document


def restore_a_document(
    context: Context, document_id: str, *, commit: str = "HEAD"
) -> RestoredDocument:
    """Put one document back as it was at `commit`: held, journalled,
    restore, commit.

    Recorded under the collection it lands in, so `corpus history
    --collection` finds it by the route that found its removal.
    """
    repository = Repository(context.corpus_root)
    with exclusively(context.corpus_root):
        record_what_was_not_recorded(context)
        path = document_path_at(repository, commit, document_id)
        with journalled(context.corpus_root, "restore", [path] if path else []):
            restored = restore_document(repository, document_id, commit=commit)
            sealed_again(context, [restored.path])
            head = restored.path.split("/", 1)[0]
            repository.commit(
                "restore",
                scope=head if head in COLLECTION_NAMES else "corpus",
                summary=outcome_summary({Outcome.ADDED: 1}),
            )
    return restored


@dataclass(frozen=True, slots=True)
class ReturnedCorpus:
    """What returning the corpus to a point did."""

    commit: str
    added: int
    removed: int
    changed: int
    # The commit recording what was on disk and not yet in history, when
    # there was any: returning to it undoes the return without loss.
    recorded: str | None


def return_corpus_to(context: Context, commit: str) -> ReturnedCorpus:
    """Make the corpus's documents as they were at `commit`, and record it.

    Held exclusively: hand deletions put back as every write does;
    **whatever else is not yet recorded is recorded first**, as
    `record(corpus)`, because a return replaces the working tree and
    kennis never discards an edit on its own initiative; then the three
    collections are returned and the return committed as
    `return(corpus): to <commit>, ...` - itself a point, so a return is
    undone by returning to the point before it. The index is left as
    built (see `history.return_to`).
    """
    repository = Repository(context.corpus_root)
    with exclusively(context.corpus_root):
        restore_hand_deletions(context)
        recorded = record_what_was_not_recorded(context)
        changes = what_a_return_changes(repository, commit)
        # Every file the return can write, assets and `.current` included:
        # with the tree just recorded, what differs from the point is
        # exactly what git is about to rewrite.
        touched = [
            path
            for name in COLLECTION_NAMES
            for _, path in repository.diff_names(changes.commit, scope=name)
        ]
        with journalled(context.corpus_root, "return", touched):
            return_to(repository, changes.commit)
            sealed_again(
                context,
                [held.path for held in (*changes.added, *changes.changed)],
            )
            repository.commit(
                "return",
                scope="corpus",
                summary=f"to {changes.commit[:8]}, "
                + commit_summary(_return_counts(changes)),
            )
    counts = _return_counts(changes)
    return ReturnedCorpus(
        commit=changes.commit,
        added=counts["added"],
        removed=counts["removed"],
        changed=counts["changed"],
        recorded=recorded,
    )


def _return_counts(changes: ReturnChanges) -> dict[str, int]:
    return {
        "added": len(changes.added),
        "removed": len(changes.removed),
        "changed": len(changes.changed),
    }


def build_indexes(
    context: Context,
    collection: str | None = None,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> IndexBuild:
    """Build one collection's index or all three: restore, build, commit.

    An empty collection is **skipped rather than attempted**:
    `build_index` refuses one by design, and two of the three are empty
    on most corpora, so asking for all of them must not fail on that
    account.
    """
    binding = binding_from(context.settings.chunking, context.settings.embedding)
    repository = Repository(context.corpus_root)
    root = index_root(context.corpus_root)
    built: list[BuiltIndex] = []
    busy: list[str] = []

    # **The corpus is held twice and briefly, not once and for the
    # duration.** A build takes minutes; holding the corpus across it
    # would keep every note and every read waiting (#167). Each build
    # takes its own index lock inside `build_index`, so the index is
    # still guarded - what is released is the documents, which a build
    # only reads.
    with exclusively(context.corpus_root):
        put_back = restore_hand_deletions(context)
        # Not through `publish`, so recorded here: the index commit below
        # stages with `git add --all .` as well.
        record_what_was_not_recorded(context)
        if restored is not None:
            restored.extend(put_back)

    for name in [collection] if collection else list(COLLECTION_NAMES):
        target = Collection(root=context.corpus_root, name=name)
        if not target.contents().documents:
            continue
        try:
            report = build_index(
                CollectionLoader(target),
                index_root=root,
                binding=binding,
                events=events,
                embed_batch_size=context.settings.embedding.batch_size,
                repository=repository,
            )
        except IndexBusy:
            busy.append(name)
            continue
        built.append(
            BuiltIndex(
                collection=name,
                documents=report.document_count,
                chunks=report.chunk_count,
                elapsed_seconds=report.elapsed_seconds,
            )
        )

    documents = sum(index.documents for index in built)
    chunks = sum(index.chunks for index in built)
    with exclusively(context.corpus_root):
        # One commit for one user action, with what it actually built in
        # the subject rather than a tally of outcomes, which an index has
        # none of. It waits for a publish under way rather than giving up.
        repository.commit(
            "index",
            scope=collection or "corpus",
            summary=commit_summary({"documents": documents, "chunks": chunks}),
        )

    return IndexBuild(
        built=built,
        busy=tuple(busy),
        model_kind=binding.model.kind if binding.model else None,
        model_name=binding.model.model if binding.model else None,
    )


def synchronise_corpus(
    context: Context,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> CorpusSync:
    """Converge the corpus with every installed pack: restore, sync in a
    mirror, publish.

    Uses the network: a pack's papers are fetched by identifier and its
    documentation sites are crawled, which is what separates this from
    `kennis pack install`.
    """

    def synced(staged: Context, sink: EventSink | None) -> CorpusSync:
        return sync_corpus(
            staged.corpus_root,
            events=sink,
            request_delay_seconds=context.settings.literature.request_delay,
            unpaywall_email=context.settings.literature.unpaywall_email,
            # The store is read where it is: the mirror holds only the
            # three collections.
            store_root=context.corpus_root,
        )

    return _prepared_then_published(
        context,
        synced,
        operation="sync",
        scope="corpus",
        summary=lambda result: describe_sync_summary(result.counts),
        events=events,
        restored=restored,
    )


def supply_a_pack_paper(
    context: Context,
    address: str,
    path: Path,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> AddReport:
    """Add a pack's paper from a file the person supplied, after a sync
    could not fetch it: restore, add in a mirror, publish. The pack owns
    it, as it owns what a sync fetches (Brian, 2026-10-26)."""

    def supplied(staged: Context, sink: EventSink | None) -> AddReport:
        return supply_paper(
            staged.corpus_root,
            address,
            path,
            events=sink,
            store_root=context.corpus_root,
        )

    return _prepared_then_published(
        context,
        supplied,
        operation="add",
        scope="literature",
        summary=lambda report: outcome_summary(report.counts),
        events=events,
        restored=restored,
    )


def synchronise_bundle(
    bundle: Path, context: Context, *, events: EventSink | None = None
) -> BundleSync:
    """Converge one project's bundle with every installed pack.

    Neither lock nor commit. **kennis does not commit here**: the bundle
    is in the user's repository. And it takes no corpus lock because it
    only reads the pack store, while writing into a directory no other
    kennis process is touching.
    """
    return sync_bundle(bundle, context.corpus_root, events=events)


@dataclass(frozen=True, slots=True)
class BundleIndexBuild:
    """What `context index` built, and with which model - None for the
    lexical index a bundle has by default (design section 13). The model's
    two fields are quoted, as `IndexBuild`'s are."""

    report: BuildReport
    model_kind: str | None = None
    model_name: str | None = None


def context_model(context: Context) -> ModelBinding | None:
    """The embedding model a bundle index is built with, if any.

    `binding_from` answers `model=None` when the backend is `none`, so
    asking for hybrid without a backend yields a lexical index rather than
    a failure - the corpus behaves the same way.
    """
    settings = context.settings
    if settings.retrieval.context_method == "bm25":
        return None
    return binding_from(settings.chunking, settings.embedding).model


def index_a_bundle(
    context: Context, bundle: Path, *, events: EventSink | None = None
) -> BundleIndexBuild:
    """Build one project's index with the settings' chunking and model.

    No lock and no commit, as `index_bundle` says: the bundle is the
    person's, and a build publishes by one pointer swap.
    """
    model = context_model(context)
    report = index_bundle(
        bundle,
        chunking=chunk_parameters(context.settings.chunking),
        model=model,
        events=events,
        embed_batch_size=context.settings.embedding.batch_size,
    )
    if model is None:
        return BundleIndexBuild(report)
    return BundleIndexBuild(report, model_kind=model.kind, model_name=model.model)


def declare_bundle_packs(
    bundle: Path,
    added: Sequence[str] = (),
    dropped: Sequence[str] = (),
    *,
    clear: bool = False,
) -> tuple[str, ...]:
    """Add to, drop from or clear what a project declares, and say what it
    declares now. Ids are added, never put in place of the rest, so a
    command printed for one pack cannot drop another (#518)."""
    kept = (
        () if clear else [one for one in declared_packs(bundle) if one not in dropped]
    )
    return declare_packs(bundle, [*kept, *added])


@dataclass(frozen=True, slots=True)
class BundleResetPreview:
    """What `context reset` would remove: the files a pack owns, relative
    to the bundle, and whether there is an index. Asked of the engine's own
    rule rather than restated, so the prompt offers exactly what goes."""

    owned: tuple[str, ...]
    has_index: bool


def what_a_reset_removes(bundle: Path) -> BundleResetPreview:
    return BundleResetPreview(
        owned=tuple(
            path.relative_to(bundle).as_posix() for path in removable_documents(bundle)
        ),
        has_index=index_root_for(bundle).is_dir(),
    )


def install_a_pack(
    context: Context, path: Path, *, events: EventSink | None = None
) -> PackInstall:
    """Record what a provider declared: lock, install.

    **No commit.** The store lives under the corpus root but is not the
    corpus's tracked content, and nothing is materialised into a
    collection until a sync. The lock is taken because a sync reads the
    store while holding it.
    """
    with exclusively(context.corpus_root):
        return install_pack(context.corpus_root, path, events=events)


def uninstall_a_pack(
    context: Context, pack_id: str, *, events: EventSink | None = None
) -> PackRemoval:
    """Drop a pack from the store: lock, remove.

    No commit, as for an install: the store is not tracked content, and
    the documents the pack put in the corpus stay until a sync converges
    them. The lock is taken because a sync reads the store while holding it.
    """
    with exclusively(context.corpus_root):
        return uninstall_pack(context.corpus_root, pack_id, events=events)


def back_up_corpus(
    context: Context,
    folder: Path,
    password: str,
    *,
    events: EventSink | None = None,
) -> BackupReport:
    """Write the encrypted backup: lock, write, test, replace.

    The corpus is held to read throughout: a publish landing during the
    write would put half of it in the archive's `.git`. No commit,
    because nothing in the corpus changes.
    """
    with shared(context.corpus_root):
        return write_backup(context.corpus_root, folder, password, events=events)


__all__ = [
    "BuiltIndex",
    "BundleIndexBuild",
    "BundleResetPreview",
    "GroupBlock",
    "IndexBuild",
    "RemovedVersion",
    "ReturnedCorpus",
    "add_documents",
    "add_in_groups",
    "back_up_corpus",
    "build_indexes",
    "context_model",
    "copy_a_document",
    "declare_bundle_packs",
    "index_a_bundle",
    "install_a_pack",
    "make_docs_version_current",
    "move_a_document",
    "record_what_was_not_recorded",
    "remove_a_document",
    "remove_docs_version",
    "restore_a_document",
    "restore_hand_deletions",
    "return_corpus_to",
    "supply_a_pack_paper",
    "synchronise_bundle",
    "synchronise_corpus",
    "uninstall_a_pack",
    "what_a_reset_removes",
]
