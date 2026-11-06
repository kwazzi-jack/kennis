"""The words for tags (#625), shared by the command line and the window."""

from __future__ import annotations

import shlex

from kennis.tagging import DETACHED, MISSING, UNCHECKED, TaggedTarget


def joined_names(names: tuple[str, ...]) -> str:
    """`calibration, to-cite`."""
    return ", ".join(names)


def already_tagged(names: tuple[str, ...]) -> str:
    return f"already tagged {joined_names(names)}"


def not_tagged(names: tuple[str, ...]) -> str:
    return f"was not tagged {joined_names(names)}"


def coloured(name: str, shown: str, chosen: str | None) -> str:
    """`calibration: purple`, or `calibration: teal, derived from its name`."""
    if chosen is None:
        return f"{name}: {shown}, derived from its name"
    return f"{name}: {shown}"


def target_state(target: TaggedTarget) -> str | None:
    """What is wrong with a target, or None when it is where it was put."""
    if target.state == DETACHED:
        return "detached: its words are no longer in the document"
    if target.state == MISSING:
        return "the document is no longer held"
    if target.state == UNCHECKED:
        return "not checked: the document is not in an index"
    return None


def untag_command(name: str, target: TaggedTarget) -> str:
    """The command that takes `name` from `target`, as it runs when typed."""
    return f"kennis untag {shlex.quote(name)} {shlex.quote(target.link)}"


def target_title(target: TaggedTarget) -> str:
    """The target's title, or what names it when it has none."""
    title = target.title or target.document
    if target.project is not None:
        return f"{title} ({target.project})"
    return title


__all__ = [
    "already_tagged",
    "coloured",
    "joined_names",
    "not_tagged",
    "target_state",
    "target_title",
    "untag_command",
]
