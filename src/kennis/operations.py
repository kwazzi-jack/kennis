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

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kennis.context import Context
from kennis.engine.context.sync import BundleSync, sync_bundle
from kennis.engine.corpus.add import (
    AddOptions,
    AddReport,
    add_docs,
    add_literature,
    add_notes,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync, sync_corpus
from kennis.engine.events import EventSink
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

    `describes` is the binding as a phrase only in the sense that the
    model's kind and name are two fields kennis is quoting; a front end
    that wants to say "using ..." has both, and one that wants to say
    nothing ignores them. `model` is None for a lexical-only binding,
    which is a different sentence rather than an empty one.
    """

    built: list[BuiltIndex]
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
        report = _ADDERS[destination](target, identifiers, options, events=events)
        Repository(context.corpus_root).commit(
            "add", scope=destination, summary=outcome_summary(report.counts)
        )
    return report


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
    with corpus_lock(context.corpus_root):
        put_back = restore_hand_deletions(context)
        if restored is not None:
            restored.extend(put_back)
        for name in [collection] if collection else list(COLLECTION_NAMES):
            target = Collection(root=context.corpus_root, name=name)
            if not target.contents().documents:
                continue
            report = build_index(
                CollectionLoader(target),
                index_root=root,
                binding=binding,
                events=events,
                embed_batch_size=context.settings.embedding.batch_size,
                repository=repository,
            )
            built.append(
                BuiltIndex(
                    collection=name,
                    documents=report.document_count,
                    chunks=report.chunk_count,
                    elapsed_seconds=report.elapsed_seconds,
                )
            )
        result = IndexBuild(
            built=built,
            model_kind=binding.model.kind if binding.model else None,
            model_name=binding.model.model if binding.model else None,
        )
        # One commit for one user action, with what it actually built in
        # the subject rather than a tally of outcomes, which an index has
        # none of.
        repository.commit(
            "index",
            scope=collection or "corpus",
            summary=commit_summary(
                {"documents": result.documents, "chunks": result.chunks}
            ),
        )
    return result


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
        result = sync_corpus(
            context.corpus_root,
            events=events,
            request_delay_seconds=context.settings.literature.request_delay,
        )
        Repository(context.corpus_root).commit(
            "sync", scope="notes", summary=describe_sync_summary(result.counts)
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


__all__ = [
    "BuiltIndex",
    "IndexBuild",
    "add_documents",
    "build_indexes",
    "install_a_pack",
    "restore_hand_deletions",
    "synchronise_bundle",
    "synchronise_corpus",
]
