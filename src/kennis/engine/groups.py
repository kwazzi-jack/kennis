"""A group is a folder inside its collection, and nothing else.

Every writer joins a group onto a directory - a collection, or a bundle -
and until this module none of them checked it: `../../outside` wrote
beside the corpus and an absolute path wrote wherever it named. The MCP
`remember` tool takes `group` from an agent, and a pack's `group` arrives
from outside, so the rule is the engine's and every join goes through it.

No imports from the rest of the engine beyond the error, so the pack
schema can use the same rule as the writers.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from kennis.engine.errors import InputError


def group_problem(group: str) -> str | None:
    """Why `group` cannot be a folder inside a collection, or None.

    Checked as both path flavours, as a pack's `source` is: a group is
    typed on one platform and may be written on another, `C:\\x` and
    `..\\x` are single filenames to Linux, and `/x` has no drive and so is
    relative to Windows (#385, #403).

    A segment beginning with a dot is refused too, though it stays inside:
    `iter_documents` treats a dot-prefixed name as bookkeeping, so a
    document filed there would be written and then never listed, searched
    or found again - the reason `title_filename` strips a leading dot.
    """
    flavours = (PurePosixPath(group), PureWindowsPath(group))
    if any(path.anchor for path in flavours):
        return "is absolute"
    if group.startswith("~"):
        return "names a home directory"
    if any(".." in path.parts for path in flavours):
        return "climbs out of its collection"
    if any(part.startswith(".") for path in flavours for part in path.parts):
        return "has a part beginning with a dot, which kennis never lists"
    return None


def checked_group(group: str | None) -> str | None:
    """`group` as given, or `InputError` saying why it cannot be one."""
    if not group:
        return group
    problem = group_problem(group)
    if problem is not None:
        raise InputError(
            f"the group '{group}' {problem}; a group is a folder inside its collection"
        )
    return group


def group_directory(base: Path, group: str | None) -> Path:
    """The directory `group` names beneath `base`; `base` for no group."""
    checked = checked_group(group)
    return base / checked if checked else base


__all__ = ["checked_group", "group_directory", "group_problem"]
