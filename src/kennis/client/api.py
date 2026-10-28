"""Each operation a command calls, as a typed function (14c).

A command calls `api.sweep(...)` and gets a `Sweep`, so no command spells
an operation's name or its result's type, and the name and the type are
stated once, here, beside each other. Every function takes the corpus
root, which is what finds the service; `connect` is looked up at call
time, so the tests' in-process service is what every function reaches.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from kennis.client import connection
from kennis.client.calls import Answered, Notice, call
from kennis.engine.history.outofband import OutOfBandChange

if TYPE_CHECKING:
    from kennis.engine.backup import BackupReport
    from kennis.engine.context.bundle import BundleCreated
    from kennis.engine.context.notes import BundleNote
    from kennis.engine.context.projects import Project
    from kennis.engine.context.reset import BundleReset
    from kennis.engine.context.status import BundleStatus
    from kennis.engine.context.sync import BundleSync
    from kennis.engine.corpus.add import AddOptions, AddReport
    from kennis.engine.corpus.collection import CollectionContents
    from kennis.engine.corpus.document import Document
    from kennis.engine.corpus.sync import CorpusSync
    from kennis.engine.docs.versions import ProjectVersions
    from kennis.engine.events import EventSink
    from kennis.engine.history.history import (
        HistoryEntry,
        RestoredDocument,
        ReturnChanges,
    )
    from kennis.engine.pack.installed import PackListing, PackRemoval
    from kennis.engine.pack.store import PackInstall
    from kennis.engine.rag.models import Filter
    from kennis.engine.rag.search import ChunkRange
    from kennis.engine.remember import RememberReport
    from kennis.finding import DocumentRead, Found, PassageRead
    from kennis.holdings import CollectionTree, CorpusStatus
    from kennis.operations import (
        BundleIndexBuild,
        BundleResetPreview,
        IndexBuild,
        RemovedVersion,
        ReturnedCorpus,
    )
    from kennis.render.hits import Hit
    from kennis.retrieval import Sweep

type Waiting = Callable[[Notice], None]


def _read[Result](
    corpus_root: Path, name: str, arguments: Mapping[str, object], returns: type[Result]
) -> Result:
    answered = call(connection.connect(corpus_root), name, arguments, returns=returns)
    return cast(Result, answered.result)


def _read_as(
    corpus_root: Path, name: str, arguments: Mapping[str, object], hint: object
) -> object:
    """A read whose result is a parametrised type, such as `list[Hit]`: the
    hint carries the element type the wire needs to rebuild each one."""
    return call(connection.connect(corpus_root), name, arguments, returns=hint).result


@dataclass(frozen=True, slots=True)
class Written[Result]:
    """A write's result, and the documents deleted by hand that it put back
    first - which a command reports above its own lines."""

    result: Result
    restored: list[OutOfBandChange]


def _write[Result](
    corpus_root: Path,
    name: str,
    arguments: Mapping[str, object],
    returns: type[Result],
    *,
    events: EventSink | None,
    on_waiting: Waiting | None,
) -> Written[Result]:
    answered: Answered = call(
        connection.connect(corpus_root),
        name,
        arguments,
        returns=returns,
        events=events,
        on_waiting=on_waiting,
    )
    return Written(result=cast(Result, answered.result), restored=answered.restored)


def add(
    corpus_root: Path,
    destination: str,
    identifiers: Sequence[str],
    options: AddOptions,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[AddReport]:
    from kennis.engine.corpus.add import AddReport

    return _write(
        corpus_root,
        "add",
        {
            "destination": destination,
            "identifiers": list(identifiers),
            "options": options,
        },
        AddReport,
        events=events,
        on_waiting=on_waiting,
    )


def sync_corpus(
    corpus_root: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[CorpusSync]:
    from kennis.engine.corpus.sync import CorpusSync

    return _write(
        corpus_root, "sync_corpus", {}, CorpusSync, events=events, on_waiting=on_waiting
    )


def supply_paper(
    corpus_root: Path,
    address: str,
    path: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[AddReport]:
    """A pack's paper a sync could not fetch, added from `path` as the
    pack's own."""
    from kennis.engine.corpus.add import AddReport

    return _write(
        corpus_root,
        "supply_paper",
        {"address": address, "path": path},
        AddReport,
        events=events,
        on_waiting=on_waiting,
    )


def index(
    corpus_root: Path,
    collection: str | None,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[IndexBuild]:
    from kennis.operations import IndexBuild

    return _write(
        corpus_root,
        "index",
        {"collection": collection},
        IndexBuild,
        events=events,
        on_waiting=on_waiting,
    )


def sweep(
    corpus_root: Path,
    question: str,
    *,
    scopes: Sequence[str],
    named: bool,
    top_k: int | None,
    filters: list[Filter] | None,
    mode: str | None,
    versions: Sequence[str],
    bundle: Path | None,
    others: Sequence[Path] = (),
) -> Sweep:
    from kennis.retrieval import Sweep

    return _read(
        corpus_root,
        "sweep",
        {
            "question": question,
            "scopes": list(scopes),
            "named": named,
            "top_k": top_k,
            "filters": filters,
            "mode": mode,
            "versions": list(versions),
            "bundle": bundle,
            "others": list(others),
        },
        Sweep,
    )


def search_scope(
    corpus_root: Path,
    collection: str,
    question: str,
    *,
    top_k: int,
    versions: Sequence[str],
    bundle: Path | None,
    others: Sequence[Path] = (),
) -> list[Hit]:
    from kennis.render.hits import Hit

    return cast(
        list[Hit],
        _read_as(
            corpus_root,
            "search_scope",
            {
                "collection": collection,
                "question": question,
                "top_k": top_k,
                "versions": list(versions),
                "bundle": bundle,
                "others": list(others),
            },
            list[Hit],
        ),
    )


def found(corpus_root: Path, handle: str, collection: str | None) -> Found:
    from kennis.finding import Found

    return _read(
        corpus_root, "found", {"handle": handle, "collection": collection}, Found
    )


def read_document(
    corpus_root: Path, handle: str, collection: str | None, *, frontmatter: bool
) -> DocumentRead:
    from kennis.finding import DocumentRead

    return _read(
        corpus_root,
        "read_document",
        {"handle": handle, "collection": collection, "frontmatter": frontmatter},
        DocumentRead,
    )


def read_passage(
    corpus_root: Path, handle: str, collection: str | None, *, chunks: ChunkRange
) -> PassageRead:
    from kennis.finding import PassageRead

    return _read(
        corpus_root,
        "read_passage",
        {"handle": handle, "collection": collection, "chunks": chunks},
        PassageRead,
    )


def status(corpus_root: Path) -> CorpusStatus:
    from kennis.holdings import CorpusStatus

    return _read(corpus_root, "status", {}, CorpusStatus)


def contents(corpus_root: Path, collection: str) -> CollectionContents:
    from kennis.engine.corpus.collection import CollectionContents

    return _read(
        corpus_root, "contents", {"collection": collection}, CollectionContents
    )


def tree(corpus_root: Path, collection: str | None) -> list[CollectionTree]:
    from kennis.holdings import CollectionTree

    trees = _read_as(
        corpus_root, "tree", {"collection": collection}, list[CollectionTree]
    )
    return cast(list[CollectionTree], trees)


def history(
    corpus_root: Path, collection: str | None, limit: int
) -> list[HistoryEntry]:
    from kennis.engine.history.history import HistoryEntry

    entries = _read_as(
        corpus_root,
        "history",
        {"collection": collection, "limit": limit},
        list[HistoryEntry],
    )
    return cast(list[HistoryEntry], entries)


def docs_versions(corpus_root: Path) -> dict[str, ProjectVersions]:
    from kennis.engine.docs.versions import ProjectVersions

    held = _read_as(corpus_root, "docs_versions", {}, dict[str, ProjectVersions])
    return cast(dict[str, ProjectVersions], held)


def version_pages(corpus_root: Path, project: str, version: str) -> int:
    return _read(
        corpus_root, "version_pages", {"project": project, "version": version}, int
    )


def return_preview(corpus_root: Path, commit: str) -> ReturnChanges:
    from kennis.engine.history.history import ReturnChanges

    return _read(corpus_root, "return_preview", {"commit": commit}, ReturnChanges)


def copy_document(
    corpus_root: Path, handle: str, collection: str | None
) -> Written[Document]:
    from kennis.engine.corpus.document import Document

    return _write(
        corpus_root,
        "copy_document",
        {"handle": handle, "collection": collection},
        Document,
        events=None,
        on_waiting=None,
    )


def remove_document(
    corpus_root: Path, handle: str, collection: str | None
) -> Written[Document]:
    from kennis.engine.corpus.document import Document

    return _write(
        corpus_root,
        "remove_document",
        {"handle": handle, "collection": collection},
        Document,
        events=None,
        on_waiting=None,
    )


def remove_version(
    corpus_root: Path, project: str, version: str
) -> Written[RemovedVersion]:
    from kennis.operations import RemovedVersion

    return _write(
        corpus_root,
        "remove_version",
        {"project": project, "version": version},
        RemovedVersion,
        events=None,
        on_waiting=None,
    )


def make_version_current(corpus_root: Path, project: str, version: str) -> None:
    _write(
        corpus_root,
        "make_version_current",
        {"project": project, "version": version},
        type(None),
        events=None,
        on_waiting=None,
    )


def move_document(
    corpus_root: Path,
    handle: str,
    *,
    group: str | None,
    title: str | None,
    collection: str | None,
) -> Written[Document]:
    from kennis.engine.corpus.document import Document

    return _write(
        corpus_root,
        "move_document",
        {"handle": handle, "group": group, "title": title, "collection": collection},
        Document,
        events=None,
        on_waiting=None,
    )


def restore_document(
    corpus_root: Path, document_id: str, commit: str
) -> Written[RestoredDocument]:
    from kennis.engine.history.history import RestoredDocument

    return _write(
        corpus_root,
        "restore_document",
        {"document_id": document_id, "commit": commit},
        RestoredDocument,
        events=None,
        on_waiting=None,
    )


def return_corpus(corpus_root: Path, commit: str) -> Written[ReturnedCorpus]:
    from kennis.operations import ReturnedCorpus

    return _write(
        corpus_root,
        "return_corpus",
        {"commit": commit},
        ReturnedCorpus,
        events=None,
        on_waiting=None,
    )


def install_pack(
    corpus_root: Path,
    path: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[PackInstall]:
    from kennis.engine.pack.store import PackInstall

    return _write(
        corpus_root,
        "install_pack",
        {"path": path.resolve()},
        PackInstall,
        events=events,
        on_waiting=on_waiting,
    )


def uninstall_pack(
    corpus_root: Path,
    pack_id: str,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[PackRemoval]:
    from kennis.engine.pack.installed import PackRemoval

    return _write(
        corpus_root,
        "uninstall_pack",
        {"pack_id": pack_id},
        PackRemoval,
        events=events,
        on_waiting=on_waiting,
    )


def pack_listing(corpus_root: Path) -> PackListing:
    from kennis.engine.pack.installed import PackListing

    return _read(corpus_root, "pack_listing", {}, PackListing)


def sync_bundle(
    corpus_root: Path,
    bundle: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[BundleSync]:
    from kennis.engine.context.sync import BundleSync

    return _write(
        corpus_root,
        "sync_bundle",
        {"bundle": bundle.resolve()},
        BundleSync,
        events=events,
        on_waiting=on_waiting,
    )


# A project's bundle (14e). Each path is sent absolute: the service runs
# elsewhere (#508).


def init_bundle(corpus_root: Path, folder: Path) -> BundleCreated:
    from kennis.engine.context.bundle import BundleCreated

    return _write(
        corpus_root,
        "init_bundle",
        {"folder": folder.resolve()},
        BundleCreated,
        events=None,
        on_waiting=None,
    ).result


def index_bundle(
    corpus_root: Path,
    bundle: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> BundleIndexBuild:
    from kennis.operations import BundleIndexBuild

    return _write(
        corpus_root,
        "index_bundle",
        {"bundle": bundle.resolve()},
        BundleIndexBuild,
        events=events,
        on_waiting=on_waiting,
    ).result


def declare_packs(
    corpus_root: Path,
    bundle: Path,
    added: Sequence[str] = (),
    dropped: Sequence[str] = (),
    *,
    clear: bool = False,
) -> tuple[str, ...]:
    answered = call(
        connection.connect(corpus_root),
        "declare_packs",
        {
            "bundle": bundle.resolve(),
            "added": tuple(added),
            "dropped": tuple(dropped),
            "clear": clear,
        },
        returns=tuple[str, ...],
    )
    return cast(tuple[str, ...], answered.result)


def copy_pack_file(corpus_root: Path, bundle: Path, reference: str) -> Path:
    return _write(
        corpus_root,
        "copy_pack_file",
        {"bundle": bundle.resolve(), "reference": reference},
        Path,
        events=None,
        on_waiting=None,
    ).result


def reset_bundle(corpus_root: Path, bundle: Path) -> BundleReset:
    from kennis.engine.context.reset import BundleReset

    return _write(
        corpus_root,
        "reset_bundle",
        {"bundle": bundle.resolve()},
        BundleReset,
        events=None,
        on_waiting=None,
    ).result


def remember_in_context(
    corpus_root: Path,
    bundle: Path,
    text: str,
    *,
    title: str | None = None,
    group: str | None = None,
) -> BundleNote:
    from kennis.engine.context.notes import BundleNote

    return _write(
        corpus_root,
        "remember_in_context",
        {"bundle": bundle.resolve(), "text": text, "title": title, "group": group},
        BundleNote,
        events=None,
        on_waiting=None,
    ).result


def add_project(corpus_root: Path, folder: Path) -> Project:
    from kennis.engine.context.projects import Project

    return _write(
        corpus_root,
        "add_project",
        {"folder": folder.resolve()},
        Project,
        events=None,
        on_waiting=None,
    ).result


def forget_project(corpus_root: Path, name: str) -> Project:
    from kennis.engine.context.projects import Project

    return _write(
        corpus_root,
        "forget_project",
        {"name": name},
        Project,
        events=None,
        on_waiting=None,
    ).result


def bundle_status(corpus_root: Path, bundle: Path) -> BundleStatus:
    from kennis.engine.context.status import BundleStatus

    return _read(
        corpus_root, "bundle_status", {"bundle": bundle.resolve()}, BundleStatus
    )


def reset_preview(corpus_root: Path, bundle: Path) -> BundleResetPreview:
    from kennis.operations import BundleResetPreview

    return _read(
        corpus_root, "reset_preview", {"bundle": bundle.resolve()}, BundleResetPreview
    )


def remember(
    corpus_root: Path,
    text: str,
    *,
    title: str | None,
    group: str | None,
    origin: str,
    index: bool,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[RememberReport]:
    from kennis.engine.remember import RememberReport

    return _write(
        corpus_root,
        "remember",
        {
            "text": text,
            "title": title,
            "group": group,
            "origin": origin,
            "index": index,
        },
        RememberReport,
        events=events,
        on_waiting=on_waiting,
    )


def back_up(
    corpus_root: Path,
    folder: Path,
    password: str,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[BackupReport]:
    from kennis.engine.backup import BackupReport

    return _write(
        corpus_root,
        "back_up",
        {"folder": folder.resolve(), "password": password},
        BackupReport,
        events=events,
        on_waiting=on_waiting,
    )


__all__ = [
    "Written",
    "add",
    "add_project",
    "back_up",
    "bundle_status",
    "contents",
    "copy_document",
    "copy_pack_file",
    "declare_packs",
    "docs_versions",
    "forget_project",
    "found",
    "history",
    "index",
    "index_bundle",
    "init_bundle",
    "install_pack",
    "make_version_current",
    "move_document",
    "pack_listing",
    "read_document",
    "read_passage",
    "remember",
    "remember_in_context",
    "remove_document",
    "remove_version",
    "reset_bundle",
    "reset_preview",
    "restore_document",
    "return_corpus",
    "return_preview",
    "search_scope",
    "status",
    "supply_paper",
    "sweep",
    "sync_bundle",
    "sync_corpus",
    "tree",
    "uninstall_pack",
    "version_pages",
]
