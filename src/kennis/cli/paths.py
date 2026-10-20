"""Arguments anchored where the person typed them (14c).

The service reads files in its own process, whose working directory is
the corpus root and not the person's (#508). So a command makes an
argument that names a path here - an existing file or directory, or a
filename pattern - absolute before it crosses. Anything else crosses as
typed: an arXiv identifier, a DOI and an address are not paths, and an
address may carry `?` and `*` without being a pattern. A relative name
that does not exist also crosses as typed, so the add's refusal names it
as the person wrote it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from kennis.engine._glob import looks_like_pattern


def anchored(arguments: Sequence[str]) -> list[str]:
    """`arguments` with every path relative to here made absolute."""
    here = Path.cwd()
    return [_anchored(argument, here) for argument in arguments]


def _anchored(argument: str, here: Path) -> str:
    if "://" in argument:
        return argument
    path = Path(argument).expanduser()
    if path.is_absolute():
        return str(path) if path != Path(argument) else argument
    if (here / path).exists() or looks_like_pattern(argument):
        return str(here / path)
    return argument


__all__ = ["anchored"]
