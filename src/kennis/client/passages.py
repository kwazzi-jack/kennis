"""A passage as a person or an agent names it, as a request to cite (#623).

What a search prints is what is given back: `id=X chunk=N` for a corpus
hit, `path=.context/<file> chunk=N` for this project's note,
`path=<project>/.context/<file> chunk=N` written whole for another
project's, or a `kennis://` link of either form. A pack's context is a
copy in the project's bundle (#624), named by its path like any other.
Only a client knows which project it is working in, so the bundle is found
here and sent (#508), and `cli/` and `mcp/` both call this rather than each
other.
"""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from kennis.engine.errors import KennisError

if TYPE_CHECKING:
    from kennis.citing import CiteRequest
    from kennis.links import Target


class PassageUnnamed(KennisError):
    """A path handle that names no project's bundle."""

    default_message = "this path is not in a project's .context folder"


def from_path(
    printed: str, chunk: int | None, *, here: Path | None, working: Path
) -> CiteRequest:
    """A context hit's `path=` value, as a request.

    The path is split at its last `.context` folder: what is before it is
    the project (this one's when the path starts there), what is after it
    the file in the bundle. `here` is the bundle the caller stands in and
    `working` its working directory, against which a relative project path
    is read: given rather than read here, because only `cli/` and `mcp/`
    read the working directory (#508), and this module is shared by both.
    """
    from kennis.citing import CiteRequest
    from kennis.engine.context.bundle import BUNDLE_DIRNAME

    path = PurePath(printed)
    parts = path.parts
    if BUNDLE_DIRNAME not in parts:
        raise PassageUnnamed(f"'{printed}' is not in a project's {BUNDLE_DIRNAME}")
    at = len(parts) - 1 - parts[::-1].index(BUNDLE_DIRNAME)
    inside = PurePath(*parts[at + 1 :]).as_posix() if at + 1 < len(parts) else ""
    if not inside:
        raise PassageUnnamed(f"'{printed}' names the bundle, not a file in it")
    if at == 0:
        if here is None:
            raise PassageUnnamed(
                f"'{printed}' is this project's, and this is run in no project",
                resolution="kennis context list",
            )
        bundle = here
    else:
        bundle = Path(*parts[: at + 1])
        if not bundle.is_absolute():
            bundle = working / bundle
    return CiteRequest(inside, chunk, bundle=bundle.resolve())


def from_link(target: Target) -> CiteRequest:
    """What a link names, as a request; a project by this machine's list."""
    from kennis.citing import CiteRequest
    from kennis.engine.context.projects import project_named
    from kennis.links import ContextTarget, LinkTarget

    match target:
        case LinkTarget(document_id=document_id, chunk=chunk):
            return CiteRequest(document_id, chunk)
        case ContextTarget(project=project, path=path, chunk=chunk):
            return CiteRequest(path, chunk, bundle=project_named(project).bundle)


__all__ = ["PassageUnnamed", "from_link", "from_path"]
