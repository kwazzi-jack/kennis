"""An author list, as BibLaTeX writes one (Brian, 2026-10-28).

Names are separated by ` and `; a name holding that word is protected by
braces, `{Barnes and Noble}`, and a list cut short ends `and others`, which
is a name to the list. kennis holds a paper's authors as that one string in
the corpus and as its names one an item in a pack, and goes between the two
here alone, so a braced name is one name everywhere.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

_SEPARATOR: Final = re.compile(r"\s+and\s+")


def split_names(line: str) -> list[str]:
    """The names of `line`, cut at ` and ` outside braces, each stripped and
    keeping its braces; empty names dropped."""
    names: list[str] = []
    depth = 0
    start = 0
    position = 0
    while position < len(line):
        char = line[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
        elif depth == 0 and char.isspace():
            separator = _SEPARATOR.match(line, position)
            if separator is not None:
                names.append(line[start:position])
                start = position = separator.end()
                continue
        position += 1
    names.append(line[start:])
    return [name.strip() for name in names if name.strip()]


def joined_names(names: Sequence[str]) -> str:
    return " and ".join(names)


def protected(name: str) -> str:
    """`name` in braces when it would otherwise be read as two names."""
    return name if len(split_names(name)) <= 1 else f"{{{name}}}"


def unbraced(name: str) -> str:
    """`name` as a reader sees it, the braces that protect it taken off."""
    return name.replace("{", "").replace("}", "")


def is_braced(name: str) -> bool:
    """Whether `name` is wholly in one pair of braces, which BibLaTeX reads
    as one last name."""
    if not (name.startswith("{") and name.endswith("}")):
        return False
    depth = 0
    for index, char in enumerate(name):
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth == 0 and index < len(name) - 1:
            return False
    return True


__all__ = ["is_braced", "joined_names", "protected", "split_names", "unbraced"]
