"""The narrowest place a chunk of a document can be cited by (#592, #593).

Brian's order of precedence: a figure, table or equation the chunk holds;
then its page; then the number of the heading it falls under, or of the
nearest numbered heading above that one; then that heading's words; else
nothing, and the document is cited alone.

**The page is not here yet.** A converted paper keeps no pages (#568):
MinerU's content lists give each block one, and `_collect` reads only the
markdown. It takes its place between the two kinds once it is kept.

**Read from the text, at citing time.** The chunk's offsets address
`Document.body` (as the window's marks do), so the locator is found from the
document as it is now, and adding it needed no change to the chunker and no
rebuilt index.

Every locator is approximate (#569): a converter can misread a number, and
a paper can print none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

type LocatorKind = Literal["figure", "table", "equation", "section"]


@dataclass(frozen=True, slots=True)
class Locator:
    """Where in a document: a kind CSL has a label for, and its value - a
    number as the document prints it, or a heading's words."""

    kind: LocatorKind
    value: str


# A caption line: the word, the number, then a stop, a colon, a bar or the
# end of the emphasis around them. "Figure 3 shows" is a sentence, and
# "Figures 3 and 4" is not one figure.
_CAPTION: Final = re.compile(
    r"^[ \t]*(?:\*\*|__|\*|_)?(?P<word>fig(?:ure)?\.?|table)[ \t]+"
    r"(?P<number>[A-Z]?\d+[a-z]?)"
    r"(?:(?:\*\*|__|\*|_)[ \t]*[.:|]?|[ \t]*[.:|])",
    re.IGNORECASE | re.MULTILINE,
)

_TAG: Final = re.compile(r"\\tag\*?\{(?P<number>[^{}]+)\}")

_HEADING: Final = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<words>.+?)[ \t#]*$")

_FENCE: Final = re.compile(r"^[ \t]*(```|~~~)")

# A section number as papers print it: `2`, `3.1.2`, `3.`, `A.1`, `IV.`,
# `Appendix B`. The first part of a decimal number has at most two digits,
# so `2011 observations` is not section 2011, and a lone capital letter
# counts only with a part after it or the word Appendix, so `A Method` is
# not appendix A.
_NUMBERED: Final = re.compile(
    r"^(?:appendix[ \t]+(?P<appendix>[A-Z])\b"
    r"|(?P<decimal>\d{1,2}(?:\.\d+)*)\.?(?=[ \t]|$)"
    r"|(?P<lettered>[A-Z](?:\.\d+)+)\.?(?=[ \t]|$)"
    r"|(?P<roman>[IVXL]+)\.(?=[ \t]|$))",
    re.IGNORECASE,
)

_EMPHASIS: Final = re.compile(r"(\*\*|__|\*|_)")


@dataclass(frozen=True, slots=True)
class _Heading:
    start: int
    level: int
    words: str


def locator_of(body: str, char_start: int, char_end: int) -> Locator | None:
    """The locator for the chunk at `[char_start, char_end)` of `body`."""
    held = _held_in(body[char_start:char_end])
    if held is not None:
        return held
    return _section_of(_headings_of(body), char_start)


def _held_in(text: str) -> Locator | None:
    """The first caption or equation tag in the chunk's own text."""
    found: list[tuple[int, Locator]] = []
    caption = _CAPTION.search(text)
    if caption is not None:
        word = caption.group("word").lower()
        kind: LocatorKind = "table" if word == "table" else "figure"
        found.append((caption.start(), Locator(kind, caption.group("number"))))
    tag = _TAG.search(text)
    if tag is not None:
        found.append((tag.start(), Locator("equation", tag.group("number").strip())))
    if not found:
        return None
    return min(found, key=lambda pair: pair[0])[1]


def _headings_of(body: str) -> list[_Heading]:
    """Every markdown heading outside a fenced block, in order."""
    headings: list[_Heading] = []
    fenced = False
    position = 0
    for line in body.splitlines(keepends=True):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            matched = _HEADING.match(line.rstrip("\r\n"))
            if matched is not None:
                words = _unspaced(_EMPHASIS.sub("", matched.group("words")).strip())
                headings.append(_Heading(position, len(matched.group("marks")), words))
        position += len(line)
    return headings


def _unspaced(words: str) -> str:
    """A heading set one letter at a time, `a b s t r a c t`, as its word.

    Only when every part is one character and there are at least three: a
    PDF's letter-spaced capitals reach the markdown so, and the space
    between its words is lost with them, so nothing else can be undone.
    """
    parts = words.split()
    if len(parts) >= 3 and all(len(part) == 1 for part in parts):
        return "".join(parts)
    return words


def _number_of(words: str) -> str | None:
    matched = _NUMBERED.match(words)
    if matched is None:
        return None
    return next(group for group in matched.groups() if group is not None)


def _section_of(headings: list[_Heading], char_start: int) -> Locator | None:
    """The heading in force at `char_start`, by its number or that of the
    nearest numbered heading above it, else by its words.

    The first heading of the document, at the top level, is its title: a
    citation names the document already.
    """
    if headings and headings[0].level == 1:
        headings = headings[1:]
    before = [heading for heading in headings if heading.start <= char_start]
    if not before:
        return None
    nearest = before[-1]
    level = nearest.level + 1
    for heading in reversed(before):
        if heading.level >= level:
            continue
        level = heading.level
        number = _number_of(heading.words)
        if number is not None:
            return Locator("section", number)
    return Locator("section", nearest.words)


__all__ = ["Locator", "LocatorKind", "locator_of"]
