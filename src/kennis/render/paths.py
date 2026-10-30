"""A path under the person's home directory, shown from `~`.

Brian, 2026-10-30: absolute paths made the command line's lines long for
nothing, `Created corpus at /home/brian/.local/share/kennis`. `~` means the
same in bash, zsh and PowerShell, which a path relative to the working
directory or the corpus would not: those change between commands and the
reader cannot see what they are relative to.

Applied to prose only. A command kennis prints is typed back as printed,
and a quoted `'~/x'` does not expand, so a remedy keeps its paths; and
`kennis config path` keeps its own, because `$(kennis config path)` is
expanded by no shell after the substitution.
"""

from __future__ import annotations

import re
from pathlib import Path

# What may come before the home in prose: the start, a space, an opening
# bracket or quote, `=`. Not a path character, so `/mnt/home/brian` and
# `notes/home/brian` are other paths that only contain the spelling.
_BEFORE = r"(?<![\w.~/\\-])"

# What may come after it: a separator, the end, or a character that cannot
# continue a name in prose. Not a letter, so `/home/brian2` is not
# `/home/brian`.
_AFTER = r"(?=[/\\\s'\"),:;\]]|\.(?![\w.])|$)"


def from_home(text: str, *, home: str | None = None) -> str:
    """`text` with every path under `home` (the person's, by default) shown
    from `~`.

    A Windows home is matched in both spellings, `C:\\Users\\x` and
    `C:/Users/x`, since kennis writes either. A home at the root, or none,
    shortens nothing: every absolute path would otherwise become `~`.
    """
    spelling = str(Path.home()) if home is None else home
    if spelling.strip("/\\") == "":
        return text
    for form in sorted({spelling, spelling.replace("\\", "/")}, key=len, reverse=True):
        text = re.sub(_BEFORE + re.escape(form) + _AFTER, "~", text)
    return text


__all__ = ["from_home"]
