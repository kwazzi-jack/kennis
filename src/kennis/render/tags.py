"""The words for tags (#625), shared by the command line and the window."""

from __future__ import annotations

import shlex
from typing import Final

from kennis.citing import passage_words
from kennis.render.html import drawn_text
from kennis.tagging import DETACHED, MISSING, UNCHECKED, TaggedTarget

# Long enough to tell two tagged passages apart on a line, short enough
# that a listing of many stays a listing.
OPENING_LENGTH: Final = 80


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


def opening_words(quote: str) -> str:
    """A selection's opening words for a line, as the page draws them
    (`html.drawn_text`): leading heading lines passed over, whitespace
    collapsed, cut at a word near `OPENING_LENGTH` characters."""
    words = drawn_text(passage_words(quote))
    if len(words) <= OPENING_LENGTH:
        return words
    cut = words.rfind(" ", 0, OPENING_LENGTH + 1)
    return words[: cut if cut > 0 else OPENING_LENGTH]


def untag_command(name: str, target: TaggedTarget) -> str:
    """The command that takes `name` from `target`, as it runs when typed:
    by its annotation's id, which needs neither the document nor its words
    to still be there."""
    return (
        f"kennis untag {shlex.quote(name)} "
        f"{shlex.quote('annotation=' + target.annotation)}"
    )


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
    "opening_words",
    "target_state",
    "target_title",
    "untag_command",
]
