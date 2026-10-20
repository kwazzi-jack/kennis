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
from typing import cast

from kennis.client import connection
from kennis.client.calls import Answered, call
from kennis.engine.backup import BackupReport
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.collection import CollectionContents
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.docs.versions import ProjectVersions
from kennis.engine.events import EventSink
from kennis.engine.history.history import HistoryEntry, RestoredDocument, ReturnChanges
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.pack.installed import PackListing, PackRemoval
from kennis.engine.pack.store import PackInstall
from kennis.engine.rag.models import Filter
from kennis.engine.rag.search import ChunkRange
from kennis.engine.remember import RememberReport
from kennis.finding import DocumentRead, Found, PassageRead
from kennis.holdings import CollectionTree, CorpusStatus
from kennis.operations import IndexBuild, RemovedVersion, ReturnedCorpus
from kennis.protocol.progress import Began, Queued
from kennis.render.hits import Hit
from kennis.retrieval import Sweep

type Waiting = Callable[[Queued | Began], None]


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
    return _write(
        corpus_root, "sync_corpus", {}, CorpusSync, events=events, on_waiting=on_waiting
    )


def index(
    corpus_root: Path,
    collection: str | None,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[IndexBuild]:
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
) -> Sweep:
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
) -> list[Hit]:
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
            },
            list[Hit],
        ),
    )


def found(corpus_root: Path, handle: str, collection: str | None) -> Found:
    return _read(
        corpus_root, "found", {"handle": handle, "collection": collection}, Found
    )


def read_document(
    corpus_root: Path, handle: str, collection: str | None, *, frontmatter: bool
) -> DocumentRead:
    return _read(
        corpus_root,
        "read_document",
        {"handle": handle, "collection": collection, "frontmatter": frontmatter},
        DocumentRead,
    )


def read_passage(
    corpus_root: Path, handle: str, collection: str | None, *, chunks: ChunkRange
) -> PassageRead:
    return _read(
        corpus_root,
        "read_passage",
        {"handle": handle, "collection": collection, "chunks": chunks},
        PassageRead,
    )


def status(corpus_root: Path) -> CorpusStatus:
    return _read(corpus_root, "status", {}, CorpusStatus)


def contents(corpus_root: Path, collection: str) -> CollectionContents:
    return _read(
        corpus_root, "contents", {"collection": collection}, CollectionContents
    )


def tree(corpus_root: Path, collection: str | None) -> list[CollectionTree]:
    trees = _read_as(
        corpus_root, "tree", {"collection": collection}, list[CollectionTree]
    )
    return cast(list[CollectionTree], trees)


def history(
    corpus_root: Path, collection: str | None, limit: int
) -> list[HistoryEntry]:
    entries = _read_as(
        corpus_root,
        "history",
        {"collection": collection, "limit": limit},
        list[HistoryEntry],
    )
    return cast(list[HistoryEntry], entries)


def docs_versions(corpus_root: Path) -> dict[str, ProjectVersions]:
    held = _read_as(corpus_root, "docs_versions", {}, dict[str, ProjectVersions])
    return cast(dict[str, ProjectVersions], held)


def version_pages(corpus_root: Path, project: str, version: str) -> int:
    return _read(
        corpus_root, "version_pages", {"project": project, "version": version}, int
    )


def return_preview(corpus_root: Path, commit: str) -> ReturnChanges:
    return _read(corpus_root, "return_preview", {"commit": commit}, ReturnChanges)


def claim(corpus_root: Path, handle: str) -> Written[Document]:
    return _write(
        corpus_root,
        "claim",
        {"handle": handle},
        Document,
        events=None,
        on_waiting=None,
    )


def disown(corpus_root: Path, handle: str) -> Written[Document]:
    return _write(
        corpus_root,
        "disown",
        {"handle": handle},
        Document,
        events=None,
        on_waiting=None,
    )


def remove_document(
    corpus_root: Path, handle: str, collection: str | None
) -> Written[Document]:
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
    return _write(
        corpus_root,
        "restore_document",
        {"document_id": document_id, "commit": commit},
        RestoredDocument,
        events=None,
        on_waiting=None,
    )


def return_corpus(corpus_root: Path, commit: str) -> Written[ReturnedCorpus]:
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
    return _write(
        corpus_root,
        "install_pack",
        {"path": path.resolve()},
        PackInstall,
        events=events,
        on_waiting=on_waiting,
    )


def remove_pack(
    corpus_root: Path,
    pack_id: str,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[PackRemoval]:
    return _write(
        corpus_root,
        "remove_pack",
        {"pack_id": pack_id},
        PackRemoval,
        events=events,
        on_waiting=on_waiting,
    )


def pack_listing(corpus_root: Path) -> PackListing:
    return _read(corpus_root, "pack_listing", {}, PackListing)


def sync_bundle(
    corpus_root: Path,
    bundle: Path,
    *,
    events: EventSink | None = None,
    on_waiting: Waiting | None = None,
) -> Written[BundleSync]:
    return _write(
        corpus_root,
        "sync_bundle",
        {"bundle": bundle.resolve()},
        BundleSync,
        events=events,
        on_waiting=on_waiting,
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
    "back_up",
    "claim",
    "contents",
    "disown",
    "docs_versions",
    "found",
    "history",
    "index",
    "install_pack",
    "make_version_current",
    "move_document",
    "pack_listing",
    "read_document",
    "read_passage",
    "remember",
    "remove_document",
    "remove_pack",
    "remove_version",
    "restore_document",
    "return_corpus",
    "return_preview",
    "search_scope",
    "status",
    "sweep",
    "sync_bundle",
    "sync_corpus",
    "tree",
    "version_pages",
]
