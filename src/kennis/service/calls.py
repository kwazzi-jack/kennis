"""The operations a client may call, as one table (14b).

Each entry is a function whose parameters the wire carries - a
collection's name, a document's handle, a path the client resolved, an
`AddOptions` - and which opens the service's own `Context` itself, so a
process-local value never crosses. The route reads a request's arguments
against the function's own type hints, so a request cannot hand the
service anything the signature does not take.

**A write is a job in a lane**; a read is answered on the request's own
thread, so a search is never behind a twenty-second PDF. Two parameters
are the service's to give and never a client's: `events`, the job's sink,
and `restored`, the list an operation fills with the hand deletions it put
back. A write declares whichever of them it uses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis import finding, operations, retrieval, writing
from kennis import holdings as held
from kennis.context import existing_corpus
from kennis.engine.backup import BackupReport
from kennis.engine.context import bundle as bundles
from kennis.engine.context import projects as known
from kennis.engine.context.bundle import BUNDLE_DIRNAME, BundleCreated
from kennis.engine.context.notes import BundleNote
from kennis.engine.context.packs import copy_pack_file as copied_into_bundle
from kennis.engine.context.projects import Project
from kennis.engine.context.reset import BundleReset
from kennis.engine.context.reset import reset_bundle as reset_the_bundle
from kennis.engine.context.status import BundleStatus
from kennis.engine.context.status import bundle_status as status_of_bundle
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.collection import CollectionContents
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.docs.versions import ProjectVersions
from kennis.engine.events import EventSink
from kennis.engine.history.history import HistoryEntry, RestoredDocument, ReturnChanges
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.pack.installed import PackListing, PackRemoval, list_installed
from kennis.engine.pack.store import PackInstall
from kennis.engine.rag.models import Filter
from kennis.engine.rag.search import ChunkRange
from kennis.engine.remember import INLINE_ORIGIN, RememberReport
from kennis.finding import DocumentRead, Found, PassageRead
from kennis.holdings import (
    CollectionTree,
    CorpusStatus,
    DocumentMarks,
    Holding,
)
from kennis.operations import (
    BundleIndexBuild,
    BundleResetPreview,
    GroupBlock,
    IndexBuild,
    RemovedVersion,
    ReturnedCorpus,
)
from kennis.render.hits import Hit
from kennis.retrieval import Sweep
from kennis.service.jobs import CORPUS_LANE, INDEX_LANE, PROJECTS_LANE, context_lane

# The parameters the service fills and a client may never name.
SERVICE_PARAMETERS: Final = frozenset({"events", "restored"})


def _in_the_corpus_lane(arguments: Mapping[str, object]) -> str:
    return CORPUS_LANE


def _in_the_index_lane(arguments: Mapping[str, object]) -> str:
    return INDEX_LANE


def _in_the_bundle_s_lane(arguments: Mapping[str, object]) -> str:
    return context_lane(str(arguments["bundle"]))


def _in_the_folder_s_bundle_lane(arguments: Mapping[str, object]) -> str:
    """`context init` names the folder; its bundle is the lane."""
    return context_lane(str(Path(str(arguments["folder"])) / BUNDLE_DIRNAME))


def _in_the_projects_lane(arguments: Mapping[str, object]) -> str:
    """The list of projects is the state directory's, not the corpus's, so
    adding to it does not wait behind an add of forty papers."""
    return PROJECTS_LANE


@dataclass(frozen=True, slots=True)
class Operation:
    """One entry: the function, and for a write its job's kind and lane.

    `kind` is None for a read. `lane` is given the decoded arguments,
    because a bundle's lane is named for the bundle.
    """

    function: Callable[..., object]
    kind: str | None = None
    lane: Callable[[Mapping[str, object]], str] = _in_the_corpus_lane

    @property
    def writes(self) -> bool:
        return self.kind is not None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def add(
    destination: str,
    identifiers: list[str],
    options: AddOptions,
    *,
    events: EventSink,
    restored: list[OutOfBandChange],
) -> AddReport:
    return operations.add_documents(
        existing_corpus(),
        destination,
        identifiers,
        options,
        events=events,
        restored=restored,
    )


def add_in_groups(
    blocks: list[GroupBlock],
    options: AddOptions,
    *,
    events: EventSink,
    restored: list[OutOfBandChange],
) -> AddReport:
    return operations.add_in_groups(
        existing_corpus(), blocks, options, events=events, restored=restored
    )


def back_up(folder: Path, password: str, *, events: EventSink) -> BackupReport:
    return operations.back_up_corpus(existing_corpus(), folder, password, events=events)


def index(
    collection: str | None = None,
    *,
    events: EventSink,
    restored: list[OutOfBandChange],
) -> IndexBuild:
    return operations.build_indexes(
        existing_corpus(), collection, events=events, restored=restored
    )


def install_pack(path: Path, *, events: EventSink) -> PackInstall:
    return operations.install_a_pack(existing_corpus(), path, events=events)


def remove_pack(pack_id: str, *, events: EventSink) -> PackRemoval:
    return operations.remove_a_pack(existing_corpus(), pack_id, events=events)


def make_version_current(project: str, version: str) -> None:
    operations.make_docs_version_current(existing_corpus(), project, version)


def move_document(
    handle: str,
    group: str | None,
    title: str | None = None,
    collection: str | None = None,
    *,
    restored: list[OutOfBandChange],
) -> Document:
    """`collection` None looks in all three, as a handle typed anywhere does."""
    context = existing_corpus()
    found, document = finding.resolve_document(context, handle, collection)
    return operations.move_a_document(
        context, found, document, group=group, title=title, restored=restored
    )


def remember(
    text: str,
    title: str | None = None,
    group: str | None = None,
    origin: str = INLINE_ORIGIN,
    index: bool = True,
    *,
    events: EventSink,
    restored: list[OutOfBandChange],
) -> RememberReport:
    return writing.write_note(
        existing_corpus(),
        text,
        title=title,
        group=group,
        origin=origin,
        index=index,
        events=events,
        restored=restored,
    )


def remove_document(handle: str, collection: str | None = None) -> Document:
    context = existing_corpus()
    found, document = finding.resolve_document(context, handle, collection)
    return operations.remove_a_document(context, found, document)


def copy_document(
    handle: str, collection: str | None = None, *, restored: list[OutOfBandChange]
) -> Document:
    return operations.copy_a_document(
        existing_corpus(), handle, collection, restored=restored
    )


def remove_version(project: str, version: str) -> RemovedVersion:
    return operations.remove_docs_version(existing_corpus(), project, version)


def restore_document(document_id: str, commit: str = "HEAD") -> RestoredDocument:
    return operations.restore_a_document(existing_corpus(), document_id, commit=commit)


def return_corpus(commit: str) -> ReturnedCorpus:
    return operations.return_corpus_to(existing_corpus(), commit)


def sync_bundle(bundle: Path, *, events: EventSink) -> BundleSync:
    return operations.synchronise_bundle(bundle, existing_corpus(), events=events)


def sync_corpus(*, events: EventSink, restored: list[OutOfBandChange]) -> CorpusSync:
    return operations.synchronise_corpus(
        existing_corpus(), events=events, restored=restored
    )


# A project's bundle (14e): in the person's repository, so no lock and no
# commit, and each bundle in its own lane.


def init_bundle(folder: Path) -> BundleCreated:
    return bundles.init_bundle(folder)


def index_bundle(bundle: Path, *, events: EventSink) -> BundleIndexBuild:
    return operations.index_a_bundle(existing_corpus(), bundle, events=events)


def declare_packs(
    bundle: Path,
    added: tuple[str, ...] = (),
    dropped: tuple[str, ...] = (),
    clear: bool = False,
) -> tuple[str, ...]:
    return operations.declare_bundle_packs(bundle, added, dropped, clear=clear)


def copy_pack_file(bundle: Path, reference: str) -> Path:
    return copied_into_bundle(bundle, existing_corpus().corpus_root, reference)


def reset_bundle(bundle: Path) -> BundleReset:
    return reset_the_bundle(bundle)


def remember_in_context(
    bundle: Path, text: str, title: str | None = None, group: str | None = None
) -> BundleNote:
    note, _ = writing.write_context_note(text, title=title, group=group, bundle=bundle)
    return note


def add_project(folder: Path) -> Project:
    return known.add_project(folder)


def forget_project(name: str) -> Project:
    return known.forget_project(name)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def bundle_status(bundle: Path) -> BundleStatus:
    return status_of_bundle(bundle)


def reset_preview(bundle: Path) -> BundleResetPreview:
    return operations.what_a_reset_removes(bundle)


def status() -> CorpusStatus:
    return held.corpus_status(existing_corpus())


def tree(collection: str | None = None) -> list[CollectionTree]:
    return held.corpus_tree(existing_corpus(), collection)


def history(collection: str | None = None, limit: int = 20) -> list[HistoryEntry]:
    return held.history_of(existing_corpus(), collection, limit)


def docs_versions() -> dict[str, ProjectVersions]:
    return held.docs_versions(existing_corpus())


def version_pages(project: str, version: str) -> int:
    return held.version_pages(existing_corpus(), project, version)


def return_preview(commit: str) -> ReturnChanges:
    return held.return_preview(existing_corpus(), commit)


def contents(collection: str) -> CollectionContents:
    return held.contents_of(existing_corpus(), collection)


def document_marks(collection: str) -> DocumentMarks:
    return held.document_marks(existing_corpus(), collection)


def holdings() -> list[Holding]:
    return held.holdings(existing_corpus())


def pack_listing() -> PackListing:
    return list_installed(existing_corpus().corpus_root)


def last_change() -> HistoryEntry | None:
    return held.last_change(existing_corpus())


def revision() -> str | None:
    return held.revision(existing_corpus())


def found(handle: str, collection: str | None = None) -> Found:
    return finding.found_document(existing_corpus(), handle, collection)


def read_document(
    handle: str, collection: str | None = None, frontmatter: bool = False
) -> DocumentRead:
    return finding.read_document(
        existing_corpus(), handle, collection, frontmatter=frontmatter
    )


def read_passage(
    handle: str, chunks: ChunkRange, collection: str | None = None
) -> PassageRead:
    return finding.read_passage(existing_corpus(), handle, collection, chunks=chunks)


def search_scope(
    collection: str,
    question: str,
    top_k: int = 5,
    versions: Sequence[str] = (),
    *,
    bundle: Path | None,
    others: Sequence[Path] = (),
) -> list[Hit]:
    return retrieval.search_scope(
        collection, question, top_k, versions, bundle=bundle, others=others
    )


def sweep(
    question: str,
    scopes: Sequence[str],
    named: bool,
    top_k: int | None = None,
    filters: list[Filter] | None = None,
    mode: str | None = None,
    versions: Sequence[str] = (),
    *,
    bundle: Path | None,
    others: Sequence[Path] = (),
) -> Sweep:
    return retrieval.sweep(
        question,
        scopes=scopes,
        named=named,
        top_k=top_k,
        filters=filters,
        mode=mode,
        versions=versions,
        bundle=bundle,
        others=others,
    )


OPERATIONS: Final[Mapping[str, Operation]] = {
    operation.function.__name__: operation
    for operation in (
        Operation(add, kind="add"),
        Operation(add_in_groups, kind="add"),
        Operation(back_up, kind="backup"),
        Operation(copy_document, kind="copy"),
        Operation(index, kind="index", lane=_in_the_index_lane),
        Operation(install_pack, kind="pack"),
        Operation(make_version_current, kind="version"),
        Operation(move_document, kind="move"),
        Operation(remember, kind="remember"),
        Operation(remove_document, kind="remove"),
        Operation(remove_pack, kind="pack"),
        Operation(remove_version, kind="version"),
        Operation(restore_document, kind="restore"),
        Operation(return_corpus, kind="return"),
        Operation(sync_bundle, kind="context-sync", lane=_in_the_bundle_s_lane),
        Operation(init_bundle, kind="context", lane=_in_the_folder_s_bundle_lane),
        Operation(index_bundle, kind="context-index", lane=_in_the_bundle_s_lane),
        Operation(declare_packs, kind="context", lane=_in_the_bundle_s_lane),
        Operation(copy_pack_file, kind="context", lane=_in_the_bundle_s_lane),
        Operation(reset_bundle, kind="context", lane=_in_the_bundle_s_lane),
        Operation(remember_in_context, kind="remember", lane=_in_the_bundle_s_lane),
        Operation(add_project, kind="context", lane=_in_the_projects_lane),
        Operation(forget_project, kind="context", lane=_in_the_projects_lane),
        Operation(sync_corpus, kind="sync"),
        Operation(bundle_status),
        Operation(contents),
        Operation(docs_versions),
        Operation(document_marks),
        Operation(found),
        Operation(history),
        Operation(holdings),
        Operation(pack_listing),
        Operation(last_change),
        Operation(read_document),
        Operation(read_passage),
        Operation(reset_preview),
        Operation(return_preview),
        Operation(revision),
        Operation(search_scope),
        Operation(status),
        Operation(sweep),
        Operation(tree),
        Operation(version_pages),
    )
}


__all__ = ["OPERATIONS", "SERVICE_PARAMETERS", "Operation"]
