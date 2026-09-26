"""Emptying a bundle of everything kennis put there.

Three things in a bundle were written by kennis and only two of them are
removed here.

**The index** is entirely derived and rebuilt by one command.

**A document kennis owns** - `owner` anything other than `user` - is what
this command exists for: `reset` is how a bundle polluted by pack content is
returned to a clean state before re-applying. Nothing writes such a file
yet, so today this removes none, which is a fact worth stating to a reader
rather than leaving them to discover.

**The scaffolding is not removed**, although kennis wrote it. `LANDING.md`
holds a table the file itself instructs the reader to keep current and
`.skeleton.md` is a template a project is expected to adapt; both are
kennis-written and user-maintained, so deleting them would destroy edits a
reset was never asked to touch. `init_bundle` restores a missing one on its
own, which is the command for wanting them fresh.

**A file the user hid is still removed if a pack owns it.** Renaming a
file to a dot-prefixed name keeps it out of the index; it does not
transfer ownership. Reading only the indexed files left pack content
behind in a bundle the command reported as clean. Concern #247.

**Ownership is read leniently and the asymmetry is deliberate.** A file with
no frontmatter, or with a header that will not parse, counts as the user's.
Keeping a pack's file costs a stale file that the next sync overwrites;
deleting a user's costs their writing, and a bundle lives in a repository
kennis has no history of, so there is no `restore` to undo it with.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from kennis.engine.context.bundle import (
    LANDING_FILENAME,
    SKELETON_FILENAME,
    index_root_for,
)
from kennis.engine.context.notes import bundle_files
from kennis.engine.frontmatter import split_frontmatter

USER_OWNER = "user"

# Kennis wrote these and the user maintains them, so a reset leaves them
# where they are. Excluded by name at any depth, because each directory
# may carry its own template. They used to be excluded by side effect -
# the narrower walk dropped every dot-prefixed path - and that stopped
# being true when the walk widened to see files a user had hidden.
SCAFFOLDING = frozenset({LANDING_FILENAME, SKELETON_FILENAME})


@dataclass(frozen=True, slots=True)
class BundleReset:
    """What a reset took out, as bundle-relative paths."""

    removed: tuple[str, ...]
    index_removed: bool


def owned_by_kennis(path: Path) -> bool:
    """Whether this file is kennis's to remove.

    False for anything that does not say otherwise, which is the lenient
    half of the rule in the module docstring: no header, an unreadable
    header and a missing `owner` key all mean the user's.
    """
    try:
        frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    owner = frontmatter.get("owner")
    return isinstance(owner, str) and owner != USER_OWNER


def removable_documents(bundle: Path) -> list[Path]:
    """Every document a reset would remove, in the order it removes them.

    Separate from `reset_bundle` so that a caller wanting to *say* what
    will go - a confirmation prompt - asks rather than restates. The
    command line used to carry its own copy of this rule, and when the
    engine's widened to see a file the user had hidden, the copy did not:
    the prompt found nothing, the command returned before calling the
    engine, and a reset that would have removed the file removed
    nothing.
    """
    return [
        path
        for path in bundle_files(bundle)
        if path.name not in SCAFFOLDING and owned_by_kennis(path)
    ]


def reset_bundle(bundle: Path) -> BundleReset:
    """Remove the index and every document kennis owns.

    Takes no lock and makes no commit, for the same reason the rest of
    `context/` does not: the repository is the user's.
    """
    removed: list[str] = []
    emptied: set[Path] = set()
    for path in removable_documents(bundle):
        removed.append(path.relative_to(bundle).as_posix())
        path.unlink()
        emptied.add(path.parent)

    # After the unlinks, so a directory that held only pack files is seen as
    # empty. Deepest first, so a nested pair collapses in one pass rather
    # than leaving the parent behind. A directory left standing and empty is
    # litter a reader cannot tell from one they made and have not filled.
    for directory in sorted(emptied, key=lambda path: len(path.parts), reverse=True):
        _remove_if_empty(directory, stop_at=bundle)

    index = index_root_for(bundle)
    index_removed = index.is_dir()
    if index_removed:
        _remove_tree(index)
    return BundleReset(removed=tuple(removed), index_removed=index_removed)


def _remove_if_empty(directory: Path, *, stop_at: Path) -> None:
    """Remove `directory` and any empty parent, never reaching `stop_at`."""
    current = directory
    while current != stop_at and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def _remove_tree(root: Path) -> None:
    """Delete a directory and everything under it.

    Written out rather than `shutil.rmtree` so that the one thing it is
    pointed at is visibly bounded: it is only ever called on the index
    directory, and a recursive delete in a directory the user owns is worth
    being able to read in full.
    """
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    root.rmdir()


__all__ = [
    "SCAFFOLDING",
    "USER_OWNER",
    "BundleReset",
    "owned_by_kennis",
    "removable_documents",
    "reset_bundle",
]
