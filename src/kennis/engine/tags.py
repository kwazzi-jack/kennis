"""Tag names and colours (#625, #627).

A tag is a flat, free-form name folded to lowercase (Brian, 2026-11-06):
no whitespace or comma, because those separate tags as they are typed, and
`/` an ordinary character with no hierarchy, as in the traditional systems
(Delicious, Pinboard, Zotero). What a tag is put on - a selection of a
document, or the whole of it - is an annotation, `engine/annotations.py`.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Mapping
from typing import Final

from kennis.engine.errors import TagColourRefused, TagNameRefused

# A tag's colour is one of these names (#627), whose value each theme of
# the window draws from its own measured table, or a hex colour a person
# typed (#629).
# The search scope over the comments annotations carry (#50, unit 3):
# here, beside the names, because `kennis/scopes.py` is loaded by a client
# and must not load the store to name it.
ANNOTATIONS_SCOPE: Final = "annotations"

TAG_COLOURS: Final = (
    "red",
    "orange",
    "yellow",
    "green",
    "teal",
    "blue",
    "purple",
    "pink",
)
_HEX: Final = re.compile(r"#[0-9a-f]{6}")
_SHORT_HEX: Final = re.compile(r"#[0-9a-f]{3}")


def tag_name(text: str) -> str:
    """`text` as a tag, folded, or `TagNameRefused`."""
    name = text.strip().lower()
    if not name or any(
        character.isspace() or character == "," or ord(character) < 32
        for character in name
    ):
        raise TagNameRefused(
            f"'{text}' is not a tag name: {TagNameRefused.default_message}"
        )
    return name


def split_tag_names(text: str) -> tuple[str, ...]:
    """Comma-separated names as typed, each folded, each kept once."""
    return tuple(dict.fromkeys(tag_name(part) for part in text.split(",")))


def tag_colour(text: str) -> str:
    """`text` as a tag colour: one of `TAG_COLOURS`, or a hex colour as
    `#rrggbb` (a typed `#rgb` is widened), in lowercase; otherwise
    `TagColourRefused`.

    A hex colour is kept as typed; the window moves its lightness per theme
    until it can be seen (#629), so the file says what the person chose.
    """
    colour = text.strip().lower()
    if colour in TAG_COLOURS:
        return colour
    if _SHORT_HEX.fullmatch(colour):
        colour = "#" + "".join(digit * 2 for digit in colour[1:])
    if _HEX.fullmatch(colour):
        return colour
    raise TagColourRefused(
        f"'{text}' is not a tag colour: choose one of {', '.join(TAG_COLOURS)}, "
        "or a hex colour such as #1f5fd1"
    )


def is_hex_colour(colour: str) -> bool:
    return _HEX.fullmatch(colour) is not None


def colour_of(name: str, chosen: Mapping[str, str]) -> str:
    """The colour `name` is drawn in: the one chosen, or one of
    `TAG_COLOURS` derived from the name.

    crc32 rather than `hash`, which Python seeds afresh in every process,
    so a tag keeps its colour across windows and restarts.
    """
    if name in chosen:
        return chosen[name]
    return TAG_COLOURS[zlib.crc32(name.encode("utf-8")) % len(TAG_COLOURS)]


__all__ = [
    "ANNOTATIONS_SCOPE",
    "TAG_COLOURS",
    "TagColourRefused",
    "TagNameRefused",
    "colour_of",
    "is_hex_colour",
    "split_tag_names",
    "tag_colour",
    "tag_name",
]
