"""The mutating operations, as a sequence every front end can share.

The fifth module beside `context.py`, and there for the reason the
other four are: **take the corpus lock, undo hand deletions, call the
engine, commit** is one sequence performed identically by whoever asks,
and `gui/` may not import `cli/` to get it.

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
  writes into it locks and commits.
- `install_a_pack` locks, because the store lives under the corpus
  root and a sync reads it, and does not commit, because the store is
  not the corpus's tracked content.
- `synchronise_bundle` does neither: a bundle lives inside a
  repository kennis does not own, and committing there would take over
  the user's version control.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from kennis.context import Context
from kennis.engine.backup import BackupReport, write_backup
from kennis.engine.context.sync import BundleSync, sync_bundle
from kennis.engine.corpus.add import (
    AddOptions,
    AddReport,
    add_docs,
    add_literature,
    add_notes,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, move_document
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.moving import move_target, refuse_regrouping_docs
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync, sync_corpus
from kennis.engine.errors import CorpusBusy, IndexBusy, KennisError
from kennis.engine.events import EventSink, Outcome
from kennis.engine.history.history import commit_summary, outcome_summary
from kennis.engine.history.outofband import (
    OutOfBandChange,
    detect_changes,
    restore_deletions,
)
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock
from kennis.engine.pack.store import PackInstall, install_pack
from kennis.engine.rag.binding import binding_from
from kennis.engine.rag.index import build_index
from kennis.engine.rag.loaders import CollectionLoader
from kennis.render.packs import describe_sync_summary

_ADDERS = {"notes": add_notes, "literature": add_literature, "docs": add_docs}

# The summary of a commit made for an operation that did not finish. Free
# text to `history._SUBJECT`, as every summary is.
INTERRUPTED: Final = "interrupted"


@contextlib.contextmanager
def committed_if_interrupted(
    context: Context, operation: str, *, scope: str
) -> Iterator[None]:
    """Record what an operation wrote before it failed, under its own name.

    Held inside the corpus lock around the work, before the work's own
    commit. A failure part-way - a full disk, a converter that crashed, an
    interrupt - leaves the documents already written on disk, and the next
    command's `git add --all .` would commit them under *its* name: an add's
    documents in a `remember(notes)` commit. Committed here, as
    `add(notes): interrupted`, history says which command wrote them.

    A commit that fails here is not reported over the failure that caused
    it: that is the one the person needs to see, and the documents are still
    on disk for the next commit.
    """
    try:
        yield
    except BaseException:
        with contextlib.suppress(KennisError):
            Repository(context.corpus_root).commit(
                operation, scope=scope, summary=INTERRUPTED
            )
        raise


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
    # False when the corpus was being written while the build
    # finished, so what it built is on disk and published but not yet
    # in history. Recorded rather than raised: a build costs minutes
    # and a commit costs milliseconds, and failing the whole command
    # at the last step would throw away the expensive part for the
    # cheap one. The next write commits it.
    committed: bool = True
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
    return [
        change
        for change in restore_deletions(repository, detect_changes(repository))
        if change.restored
    ]


def add_documents(
    context: Context,
    destination: str,
    identifiers: Sequence[str],
    options: AddOptions,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> AddReport:
    """Add to one collection: lock, restore, add, commit.

    `restored` is filled in place rather than returned beside the
    report, because a caller that wants both wants them in the order
    they happened and a tuple return would read as though the restore
    were part of the add. Passing None asks for the restore without
    hearing about it, which is what a caller with nowhere to print it
    means.
    """
    target = Collection(root=context.corpus_root, name=destination)
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
        if restored is not None:
            restored.extend(put_back)
        with committed_if_interrupted(context, "add", scope=destination):
            report = _ADDERS[destination](target, identifiers, options, events=events)
        Repository(context.corpus_root).commit(
            "add", scope=destination, summary=outcome_summary(report.counts)
        )
    return report


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
    """Refile or rename one document: lock, restore, move, commit.

    The sequence `corpus move` ran inside the command line, here so the
    window's tree runs the same one. A docs page is refused a group
    before the lock is taken (#101). `restored` is filled in place, as
    `add_documents` fills it, for a caller that says what came back.
    """
    refuse_regrouping_docs(collection, group)
    target = move_target(collection, document, group=group, title=title)
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
        if restored is not None:
            restored.extend(put_back)
        with committed_if_interrupted(context, "move", scope=collection.name):
            moved = move_document(
                document,
                target_md_path=target,
                updates={"title": title} if title else None,
            )
        Repository(context.corpus_root).commit(
            "move",
            scope=collection.name,
            summary=outcome_summary({Outcome.CHANGED: 1}),
        )
    return moved


def build_indexes(
    context: Context,
    collection: str | None = None,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> IndexBuild:
    """Build one collection's index or all three: lock, restore, build, commit.

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

    # **The corpus lock is taken twice and briefly, not once and for the
    # duration.** A build takes minutes; holding the corpus across it
    # meant a note written meanwhile was refused and lost, which is
    # what concern #167 is. Each build takes its own index lock inside
    # `build_index`, so the index is still guarded - what is released
    # is the documents, which a build only reads.
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
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
    committed = True
    try:
        with corpus_lock(context.corpus_root):
            # One commit for one user action, with what it actually
            # built in the subject rather than a tally of outcomes,
            # which an index has none of.
            repository.commit(
                "index",
                scope=collection or "corpus",
                summary=commit_summary({"documents": documents, "chunks": chunks}),
            )
    except CorpusBusy:
        # The build released the corpus while it ran, so something else
        # may hold it now - a `remember` from an agent is exactly the
        # case section 16 describes. The index is published and usable
        # either way; only its commit waits for the next write.
        committed = False

    return IndexBuild(
        built=built,
        busy=tuple(busy),
        committed=committed,
        model_kind=binding.model.kind if binding.model else None,
        model_name=binding.model.model if binding.model else None,
    )


def synchronise_corpus(
    context: Context,
    *,
    events: EventSink | None = None,
    restored: list[OutOfBandChange] | None = None,
) -> CorpusSync:
    """Converge the corpus with every installed pack: lock, restore, sync, commit.

    Uses the network: a pack's papers are fetched by identifier and its
    documentation sites are crawled, which is what separates this from
    `kennis pack add`.
    """
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
        if restored is not None:
            restored.extend(put_back)
        with committed_if_interrupted(context, "sync", scope="corpus"):
            result = sync_corpus(
                context.corpus_root,
                events=events,
                request_delay_seconds=context.settings.literature.request_delay,
                unpaywall_email=context.settings.literature.unpaywall_email,
            )
        Repository(context.corpus_root).commit(
            "sync", scope="corpus", summary=describe_sync_summary(result.counts)
        )
    return result


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


def install_a_pack(
    context: Context, path: Path, *, events: EventSink | None = None
) -> PackInstall:
    """Record what a provider declared: lock, install.

    **No commit.** The store lives under the corpus root but is not the
    corpus's tracked content, and nothing is materialised into a
    collection until a sync. The lock is taken because a sync reads the
    store while holding it.
    """
    with corpus_lock(context.corpus_root):
        return install_pack(context.corpus_root, path, events=events)


def back_up_corpus(
    context: Context,
    folder: Path,
    password: str,
    *,
    events: EventSink | None = None,
) -> BackupReport:
    """Write the encrypted backup: lock, write, test, replace.

    The lock is held throughout, as for anything that reads the
    repository: a commit landing during the write would put half of it
    in the archive's `.git`. No commit, because nothing in the corpus
    changes.
    """
    with corpus_lock(context.corpus_root):
        return write_backup(context.corpus_root, folder, password, events=events)


__all__ = [
    "INTERRUPTED",
    "BuiltIndex",
    "GroupBlock",
    "IndexBuild",
    "add_documents",
    "add_in_groups",
    "back_up_corpus",
    "build_indexes",
    "committed_if_interrupted",
    "install_a_pack",
    "move_a_document",
    "restore_hand_deletions",
    "synchronise_bundle",
    "synchronise_corpus",
]
