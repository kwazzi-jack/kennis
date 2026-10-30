"""Whether a relative path names a file every platform kennis runs on can hold.

A pack is written on one platform and installed on another, so the path of
every file it ships is judged by the strictest of them, Windows (#573).
Linux accepts a `:` in a name and Windows refuses to create the file; that
was ten of the TRON pack's PDFs, and `pack validate` had passed them.

**The length limit is a budget, not a Windows rule.** Windows refuses a path
over 260 characters unless long paths are enabled, which is off by
default. A pack's file is held at
`C:\\Users\\<name>\\AppData\\Local\\kennis\\kennis\\packs\\<id>\\<path>`, and
during a sync it is also written in a staging mirror inside the corpus
(`.git\\kennis-staging\\<32 hex digits>\\`) with its collection and group in
front: about 150 characters before the pack's own path, with a twenty
character account name. That leaves about 100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

type PortabilityKind = Literal[
    "reserved-character",
    "control-character",
    "reserved-name",
    "ends-in-dot-or-space",
    "too-long",
]

PORTABLE_PATH_LIMIT: Final = 100

_RESERVED_CHARACTERS: Final = frozenset('<>:"|?*\\')

# Reserved whatever follows the first dot: `nul.md` and `AUX.tar.gz` are the
# device, while `con1.md` and `console.md` are ordinary names.
_RESERVED_NAME: Final = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class PortabilityProblem:
    """Why one path is not portable, as facts for `render/` to word.

    `segment` is the part of the path at fault, empty for `too-long`, which
    is about the whole path; `character` is set for the two character kinds.
    """

    kind: PortabilityKind
    segment: str
    character: str | None = None


def portability_problem(relative: str) -> PortabilityProblem | None:
    """The first reason `relative`, a POSIX path inside a pack, could not be
    held on Windows, or None.

    Split on `/` alone, because a pack's paths are POSIX: a `\\` in one is
    part of a name, and Windows would read it as a separator.
    """
    for segment in relative.split("/"):
        for character in segment:
            if character in _RESERVED_CHARACTERS:
                return PortabilityProblem(
                    kind="reserved-character", segment=segment, character=character
                )
            if ord(character) < 32:
                return PortabilityProblem(
                    kind="control-character", segment=segment, character=character
                )
        if _RESERVED_NAME.match(segment.split(".", 1)[0]):
            return PortabilityProblem(kind="reserved-name", segment=segment)
        if segment.endswith((".", " ")) and segment not in {".", ".."}:
            return PortabilityProblem(kind="ends-in-dot-or-space", segment=segment)
    if len(relative) > PORTABLE_PATH_LIMIT:
        return PortabilityProblem(kind="too-long", segment="")
    return None


__all__ = [
    "PORTABLE_PATH_LIMIT",
    "PortabilityKind",
    "PortabilityProblem",
    "portability_problem",
]
