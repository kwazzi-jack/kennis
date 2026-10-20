"""What the left pane shows: the collections, and this project's bundle.

**Rows on every page, documents on request.** Every page draws the
collections with their counts and states - one `holdings` call, about
50 ms on a corpus of 56 documents - but not the documents inside them.
Measured, drawing every document costs about 0.7 ms each, which is most
of a second at a thousand; so a collection's documents are fetched from
`/tree/{collection}` when the reader opens it.

**Four states, not two.** An empty collection has nothing to index and
one never indexed is not stale; both differ from an index that is
merely behind. `Holding.is_current` answers "is there anything to do",
which is what a dot beside a name is for (#245).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from starlette.requests import Request

from kennis.context import existing_corpus
from kennis.engine.context.notes import bundle_documents
from kennis.engine.errors import KennisError
from kennis.engine.history.history import HistoryEntry
from kennis.gui.project import bundle_of
from kennis.holdings import Holding, holdings, installed_packs, last_change

type PaneState = Literal["empty", "none", "behind", "current"]


@dataclass(frozen=True, slots=True)
class PaneCollection:
    """One collection's row.

    `waiting` is how many of its documents a search cannot find yet:
    every document when it has never been indexed, otherwise those added
    or changed since. A document gone since does not wait for anything.
    """

    collection: str
    documents: int
    state: PaneState
    waiting: int = 0


@dataclass(frozen=True, slots=True)
class Pane:
    """Everything the pane draws on every page.

    `readable` is False when the corpus could not be read at all. The
    pane then says so in place of its rows rather than failing the page
    around it: a reader who opened the window to fix exactly that needs
    the rest of the window.

    `last_change` is the corpus's newest commit, which the strip reads
    too, so a page asks git for it once.
    """

    collections: tuple[PaneCollection, ...]
    project: str | None
    readable: bool = True
    packs: int = 0
    last_change: HistoryEntry | None = None

    @property
    def documents(self) -> int:
        """Every document the corpus holds."""
        return sum(row.documents for row in self.collections)

    @property
    def waiting(self) -> int:
        """Every document a search cannot find yet."""
        return sum(row.waiting for row in self.collections)


@dataclass(frozen=True, slots=True)
class BundleFolder:
    """One directory of the bundle and the documents directly in it.

    `name` is empty for the bundle's own top level.
    """

    name: str
    documents: tuple[str, ...]


def state_of(holding: Holding) -> PaneState:
    """Which of the four states a collection is in."""
    if holding.documents == 0:
        return "empty"
    if holding.freshness is None:
        return "none"
    return "current" if holding.is_current else "behind"


def waiting_in(holding: Holding) -> int:
    """How many of a collection's documents a search cannot find yet."""
    if holding.freshness is None:
        return holding.documents
    return holding.freshness.added + holding.freshness.changed


def pane_now(request: Request) -> Pane:
    """The pane as it is at this request, for this tab's project."""
    try:
        context = existing_corpus()
        held = holdings(context)
        packs = len(installed_packs(context))
        newest = last_change(context)
    except KennisError:
        return Pane(
            collections=(), project=project_name(bundle_of(request)), readable=False
        )
    return Pane(
        collections=tuple(
            PaneCollection(
                collection=holding.collection,
                documents=holding.documents,
                state=state_of(holding),
                waiting=waiting_in(holding),
            )
            for holding in held
        ),
        project=project_name(bundle_of(request)),
        packs=packs,
        last_change=newest,
    )


def project_name(bundle: Path | None) -> str | None:
    """The name of the project whose bundle this is, or None.

    The bundle's manifest carries no name and `.context` is the same in
    every project, so the directory holding it is what tells one project
    from another (#407).
    """
    return None if bundle is None else bundle.parent.name


def bundle_folders(bundle: Path) -> list[BundleFolder]:
    """The bundle's documents by directory, top level first.

    Paths are relative to the bundle and written with forward slashes,
    because they become `/bundle/{path}` addresses.
    """
    grouped: dict[str, list[str]] = {}
    for path in bundle_documents(bundle):
        relative = path.relative_to(bundle).as_posix()
        folder, _, _ = relative.rpartition("/")
        grouped.setdefault(folder, []).append(relative)
    return [
        BundleFolder(name=folder, documents=tuple(sorted(documents)))
        for folder, documents in sorted(
            grouped.items(), key=lambda pair: (pair[0] != "", pair[0])
        )
    ]


__all__ = [
    "BundleFolder",
    "Pane",
    "PaneCollection",
    "PaneState",
    "bundle_folders",
    "pane_now",
    "project_name",
    "state_of",
    "waiting_in",
]
