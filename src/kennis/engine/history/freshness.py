"""Whether an index still matches the corpus it was built over.

The index records **the commit it was built from**, so the question is
answered by git rather than by walking the corpus and comparing digests:

    git diff --name-status <built_from> HEAD -- <collection>/
    git status --porcelain -- <collection>/

That is `O(changed files)` rather than `O(corpus)`, exact rather than
digest-by-digest, and the added/changed/gone distinction survives intact
because it is precisely what `--name-status` returns.

Both commands are needed. The diff misses anything not yet committed, and a
document a user edited by hand is a change the index does not know about
just as surely as a committed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Literal

from kennis.engine.history.repository import Repository

type IndexState = Literal["in step", "stale", "unverifiable"]

# Why a freshness question could not be answered.
type Unverifiable = Literal["no commit recorded", "commit not in this corpus"]

# Git keeps no empty directories, so each collection holds one of these to
# survive a commit. It is not a document and must not be counted as one.
_PLACEHOLDER: Final = ".gitkeep"

# A document with assets is a directory holding this file.
_WRAPPED: Final = "content.md"


@dataclass(frozen=True, slots=True)
class Freshness:
    """How far an index has fallen behind its collection.

    **Only `stale` is a fault.** Documents *added* since the build are
    counted and deliberately do not make the state stale: between a `corpus
    add` and the `corpus index` that follows it the index holds nothing
    false, it simply holds less than the corpus does. Incomplete is not
    wrong. So serving decides on `stale` alone, while a caller asking whether
    an index is complete reads `added` as well.

    That distinction is also why there is no scheduler: a third state of
    "will be current later" is the one that misleads, because it stays true
    right up until the job did not run.
    """

    state: IndexState
    added: int = 0
    changed: int = 0
    gone: int = 0
    # Which reason applies, for `unverifiable` only. A value rather than a
    # sentence, so the two cases can be worded differently by a front end
    # without the engine knowing how they differ.
    unverifiable: Unverifiable | None = None


def index_freshness(
    repository: Repository, *, collection: str, built_from: str | None
) -> Freshness:
    """Compare a collection against the commit its index was built from."""
    if built_from is None:
        return Freshness(state="unverifiable", unverifiable="no commit recorded")
    if not repository.has_commit(built_from):
        return Freshness(state="unverifiable", unverifiable="commit not in this corpus")

    scope = f"{collection}/"
    added: set[str] = set()
    changed: set[str] = set()
    gone: set[str] = set()

    for status, path in repository.diff_names(built_from, scope=scope):
        _record(status, path, collection, added, changed, gone)
    for status, path in repository.status_names(scope=scope):
        _record(status, path, collection, added, changed, gone)

    # A document that was committed as changed and then edited again appears
    # in both answers; it is one document either way. A document added and
    # then modified is an addition, not a change, so additions win.
    changed -= added
    gone -= added

    return Freshness(
        state="stale" if (changed or gone) else "in step",
        added=len(added),
        changed=len(changed),
        gone=len(gone),
    )


def _record(
    status: str,
    path: str,
    collection: str,
    added: set[str],
    changed: set[str],
    gone: set[str],
) -> None:
    document = document_of(path, collection)
    if document is None:
        return
    if status == "A":
        added.add(document)
    elif status == "D":
        gone.add(document)
    else:
        changed.add(document)


def document_of(path: str, collection: str) -> str | None:
    """The document a changed path belongs to, or None if it is not one.

    Counted per document rather than per file: a document with assets is a
    directory holding `content.md`, so three changed paths under it are one
    changed document, not three.

    **Derived from the path rather than from the filesystem**, because a
    deleted file cannot be examined and deletions are exactly what this has
    to count.
    """
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != collection:
        return None

    relative = PurePosixPath(*parts[1:])
    if relative.name == _PLACEHOLDER:
        return None
    if relative.name == _WRAPPED or relative.suffix != ".md":
        # An asset, or the leaf of a wrapped document: either way the
        # document is the directory it sits in.
        parent = relative.parent
        return f"{collection}/{parent}" if str(parent) != "." else None
    return f"{collection}/{relative}"
