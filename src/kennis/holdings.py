"""What this machine holds, and whether the indexes still match it.

Beside `context.py`, `retrieval.py` and `logs.py`: questions every
front end asks and none of them owns. `corpus status` asks them from a
terminal and the graphical interface asks them from a page, and the
answer must not depend on which asked.

**The freshness call has a subtlety that is easy to omit.**
`index_freshness` needs `indexed=manifest.documents` as well as
`built_from`, because `built_from` is the head *before* the indexing
command's own commit - without the manifest's map, every `kennis
remember` reports the note it has just indexed as not yet indexed
(concern #245). Sharing the call is how a second front end cannot
reintroduce that.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kennis.context import Context
from kennis.engine.corpus.collection import Collection, CollectionContents
from kennis.engine.corpus.document import DocumentFacts
from kennis.engine.corpus.layout import index_root, relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.docs.versions import (
    ProjectVersions,
    pages_of_version,
    project_versions,
)
from kennis.engine.history.freshness import (
    DocumentStates,
    Freshness,
    document_states,
    index_freshness,
)
from kennis.engine.history.git import git
from kennis.engine.history.history import (
    HistoryEntry,
    ReturnChanges,
    read_history,
    what_a_return_changes,
)
from kennis.engine.history.outofband import OutOfBandChange, detect_changes
from kennis.engine.history.repository import Repository
from kennis.engine.pack.installed import InstalledPack, list_installed
from kennis.engine.rag.index import published_files, read_manifest


@dataclass(frozen=True, slots=True)
class Holding:
    """What one collection holds, and how far its index has fallen behind.

    `freshness` is None when the collection has never been indexed,
    which is a different thing from an index that is behind: there is
    nothing to be behind. A front end that conflated them would tell a
    fresh corpus its index was stale.
    """

    collection: str
    documents: int
    unreadable: int
    freshness: Freshness | None

    @property
    def is_current(self) -> bool:
        """Whether the index holds everything the collection does.

        `added` counts too. `Freshness` treats added documents as not
        making an index *stale* - it holds nothing false, just less -
        but "is there anything to do" is the question a person browsing
        is asking, and the answer there is yes.
        """
        if self.freshness is None:
            return False
        return self.freshness.state == "in step" and not self.freshness.added


def holdings(context: Context) -> list[Holding]:
    """Every collection, in the order the schema names them.

    **Recomputed only when the corpus has changed.** Counting reads every
    document's frontmatter - about a second at a thousand documents - and
    the window asks on every page and five times after every job. Whether
    anything changed is `corpus_state`, about fifteen milliseconds, so the
    answer is still derived from the corpus on each request rather than
    latched; it is only not derived twice from the same corpus.
    """
    root = context.corpus_root
    state = corpus_state(context)
    with _HELD_GUARD:
        held = _HELD.get(root)
    if held is not None and held[0] == state:
        return list(held[1])
    repository = Repository(root)
    counted = [
        _holding(context, repository, collection, state)
        for collection in COLLECTION_NAMES
    ]
    with _HELD_GUARD:
        _HELD[root] = (state, counted)
    return list(counted)


# What `holdings` last counted, per corpus, and the state it counted. Read
# before counting, so a write landing during the count leaves a state that
# differs from the next one read and is counted again, never kept.
type CorpusState = tuple[object, ...]
_HELD: dict[Path, tuple[CorpusState, list[Holding]]] = {}
_HELD_GUARD = threading.Lock()


def corpus_state(context: Context) -> CorpusState:
    """Everything a holding is computed from, cheaply enough to ask each time.

    - **the commit**, for everything recorded;
    - **every path git reports as uncommitted, with its size and time**:
      `--untracked-files=all` so a new file inside a new directory is named
      rather than its directory, and the time because a second edit to an
      already-modified document leaves the status line as it was;
    - **each index's pointer and manifest**, which git ignores and which
      freshness reads.
    """
    root = context.corpus_root
    head = git(["rev-parse", "--verify", "--quiet", "HEAD"], cwd=root).stdout
    listed = git(
        ["status", "--porcelain", "-z", "--untracked-files=all"], cwd=root
    ).records()
    uncommitted = tuple(
        (record, _stamp(root / record[3:])) for record in listed if len(record) > 3
    )
    indexes = tuple(
        _stamp(path)
        for collection in COLLECTION_NAMES
        for path in published_files(index_root(root), collection)
    )
    return (head, uncommitted, indexes)


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size)


def contents_of(
    context: Context, collection: str, *, state: CorpusState | None = None
) -> CollectionContents:
    """One collection's documents, walked again only when the corpus changed.

    For a reader, as the window is: `Collection.contents` caches nothing on
    purpose, because a command holding the lock must never read a document
    deleted underneath it, and that is still how every write reads. A page
    listing a collection - half a millisecond a document - asks this.
    `state` is `corpus_state`, for a caller that has just read it.
    """
    root = context.corpus_root
    now = state if state is not None else corpus_state(context)
    with _HELD_GUARD:
        held = _WALKED.get((root, collection))
    if held is not None and held[0] == now:
        return held[1]
    walked = Collection(root=root, name=collection).contents()
    with _HELD_GUARD:
        _WALKED[(root, collection)] = (now, walked)
    return walked


_WALKED: dict[tuple[Path, str], tuple[CorpusState, CollectionContents]] = {}


def _holding(
    context: Context, repository: Repository, collection: str, state: CorpusState
) -> Holding:
    contents = contents_of(context, collection, state=state)
    return Holding(
        collection=collection,
        documents=len(contents.documents),
        unreadable=len(contents.unreadable),
        freshness=freshness_of(context, repository, collection),
    )


def freshness_of(
    context: Context, repository: Repository, collection: str
) -> Freshness | None:
    """How far one index has fallen behind, or None if it has none."""
    manifest = read_manifest(index_root(context.corpus_root), collection)
    if manifest is None:
        return None
    return index_freshness(
        repository,
        collection=collection,
        built_from=manifest.built_from,
        indexed=manifest.documents,
    )


type DocumentState = Literal["", "unindexed", "changed"]


@dataclass(frozen=True, slots=True)
class DocumentMarks:
    """Where the index stands for each document of one collection.

    Three answers, and the difference between the first two matters: a
    collection that was **never indexed** has nothing in step, so every
    document is unindexed; one whose index **cannot be checked** - its
    commit is not in this corpus - has no per-document answer at all, and
    a tree says nothing rather than guessing. Otherwise `states` holds the
    sets `corpus status` counts, so the two cannot disagree.
    """

    never_indexed: bool
    states: DocumentStates | None

    def state_of(self, corpus_root: Path, anchor: Path) -> DocumentState:
        """One document's state, named by its wrapper or its file.

        `anchor` is spelled the way `document_of` names a document - a
        wrapped one by its directory - so it is looked up as given.
        """
        if self.never_indexed:
            return "unindexed"
        if self.states is None:
            return ""
        name = relative_to_corpus(anchor, corpus_root)
        if name in self.states.changed:
            return "changed"
        if name in self.states.added:
            return "unindexed"
        return ""


def document_marks(context: Context, collection: str) -> DocumentMarks:
    """Per-document freshness for one collection, by the same rule as
    `freshness_of`, with `indexed=manifest.documents` for the same
    reason (#245)."""
    manifest = read_manifest(index_root(context.corpus_root), collection)
    if manifest is None:
        return DocumentMarks(never_indexed=True, states=None)
    repository = Repository(context.corpus_root)
    built_from = manifest.built_from
    if built_from is None or not repository.has_commit(built_from):
        return DocumentMarks(never_indexed=False, states=None)
    return DocumentMarks(
        never_indexed=False,
        states=document_states(
            repository,
            collection=collection,
            built_from=built_from,
            indexed=manifest.documents,
        ),
    )


def installed_packs(context: Context) -> tuple[InstalledPack, ...]:
    """Every pack in the store, or nothing when there is no store yet."""
    return tuple(list_installed(context.corpus_root).packs)


def revision(context: Context) -> str | None:
    """The commit the corpus is at, or None before its first.

    What a long-lived view compares against to learn that a terminal
    has written underneath it. One `git rev-parse`, so it is cheap
    enough to answer on demand and far too expensive to poll.
    """
    return Repository(context.corpus_root).head()


def last_change(context: Context) -> HistoryEntry | None:
    """The corpus's newest commit, or None before its first.

    Read from the history rather than from this launch's jobs, because
    the history survives a restart and records what the command line
    did as well. Its `commit` is also the head.
    """
    newest = read_history(Repository(context.corpus_root), limit=1)
    return newest[0] if newest else None


# ---------------------------------------------------------------------------
# What the command line's corpus reports show (14c)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CollectionStatus:
    """One collection as `corpus status` reports it.

    `facts` are read through `survey`, the lenient reader, on purpose:
    `DocumentInvalid` names `corpus status` as its resolution, so a status
    that used the strict reader would die on exactly the corpus it exists
    to diagnose (#21). `freshness` is None when there is no index.
    """

    collection: str
    facts: list[DocumentFacts]
    freshness: Freshness | None


@dataclass(frozen=True, slots=True)
class CorpusStatus:
    """What the corpus holds, and what changed outside kennis."""

    collections: list[CollectionStatus]
    changes: list[OutOfBandChange]


def corpus_status(context: Context) -> CorpusStatus:
    repository = Repository(context.corpus_root)
    return CorpusStatus(
        collections=[
            CollectionStatus(
                collection=name,
                facts=Collection(root=context.corpus_root, name=name).survey(),
                freshness=freshness_of(context, repository, name),
            )
            for name in COLLECTION_NAMES
        ],
        changes=detect_changes(repository),
    )


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One line of a collection's tree: a group, or a document.

    `identifier` is a document's handle, or None for a document whose
    frontmatter carries none to read - one kennis cannot validate rather
    than one it cannot find.
    """

    name: str
    depth: int
    group: bool
    identifier: str | None


@dataclass(frozen=True, slots=True)
class CollectionTree:
    collection: str
    entries: list[TreeEntry]


def corpus_tree(context: Context, collection: str | None) -> list[CollectionTree]:
    """The corpus as the directories it really is, each document with its
    handle; a collection with no folder is left out.

    The identifiers come from `survey`, so a document that fails validation
    still has one: a tree is a picture of what is on disk, and a document
    kennis cannot read is exactly the one a reader needs to be shown. A
    wrapped document - `Foo/content.md` with its `images/` - is one entry,
    its wrapper, and nothing inside it is walked.
    """
    trees: list[CollectionTree] = []
    for name in [collection] if collection else list(COLLECTION_NAMES):
        found = Collection(root=context.corpus_root, name=name)
        root = found.path
        if not root.is_dir():
            continue
        identifiers = {
            (facts.wrapper_dir or facts.md_path).name: facts.identifier
            for facts in found.survey()
        }
        entries: list[TreeEntry] = []
        for path in sorted(root.rglob("*")):
            if path.name.startswith(".") or any(
                part in identifiers for part in path.parts[:-1]
            ):
                continue
            depth = len(path.relative_to(root).parts) - 1
            group = path.is_dir() and path.name not in identifiers
            entries.append(
                TreeEntry(
                    name=path.name,
                    depth=depth,
                    group=group,
                    identifier=None if group else identifiers.get(path.name),
                )
            )
        trees.append(CollectionTree(collection=name, entries=entries))
    return trees


def history_of(
    context: Context, collection: str | None, limit: int
) -> list[HistoryEntry]:
    """What kennis did to the corpus, newest first."""
    return read_history(
        Repository(context.corpus_root), collection=collection, limit=limit
    )


def docs_versions(context: Context) -> dict[str, ProjectVersions]:
    """Every docs project that has versions, with the versions held and the
    current one."""
    return project_versions(Collection(root=context.corpus_root, name="docs").path)


def version_pages(context: Context, project: str, version: str) -> int:
    """How many pages removing one docs version would remove, or the refusal
    naming the versions held: said before anything is removed."""
    return pages_of_version(
        Collection(root=context.corpus_root, name="docs").path, project, version
    )


def return_preview(context: Context, commit: str) -> ReturnChanges:
    """What returning the corpus to `commit` would put back, remove and
    change, said before it is done."""
    return what_a_return_changes(Repository(context.corpus_root), commit)


__all__ = [
    "CollectionStatus",
    "CollectionTree",
    "CorpusState",
    "CorpusStatus",
    "DocumentMarks",
    "DocumentState",
    "Holding",
    "TreeEntry",
    "contents_of",
    "corpus_state",
    "corpus_status",
    "corpus_tree",
    "docs_versions",
    "document_marks",
    "freshness_of",
    "history_of",
    "holdings",
    "installed_packs",
    "last_change",
    "return_preview",
    "revision",
    "version_pages",
]
