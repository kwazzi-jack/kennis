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

from dataclasses import dataclass

from kennis.context import Context
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.history.freshness import Freshness, index_freshness
from kennis.engine.history.repository import Repository
from kennis.engine.pack.installed import InstalledPack, list_installed
from kennis.engine.rag.index import read_manifest


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
    """Every collection, in the order the schema names them."""
    repository = Repository(context.corpus_root)
    return [
        _holding(context, repository, collection) for collection in COLLECTION_NAMES
    ]


def _holding(context: Context, repository: Repository, collection: str) -> Holding:
    contents = Collection(root=context.corpus_root, name=collection).contents()
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


__all__ = [
    "Holding",
    "freshness_of",
    "holdings",
    "installed_packs",
    "revision",
]
