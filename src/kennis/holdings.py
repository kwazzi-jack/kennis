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
from kennis.engine.corpus.layout import index_root, relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.history.freshness import (
    DocumentStates,
    Freshness,
    document_states,
    index_freshness,
)
from kennis.engine.history.git import git
from kennis.engine.history.history import HistoryEntry, read_history
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


__all__ = [
    "CorpusState",
    "DocumentMarks",
    "DocumentState",
    "Holding",
    "contents_of",
    "corpus_state",
    "document_marks",
    "freshness_of",
    "holdings",
    "installed_packs",
    "last_change",
    "revision",
]
