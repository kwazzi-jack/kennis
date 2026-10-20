"""Which project's bundle a tab shows (#508).

The service is shared by every client in every directory, so the window
cannot find "the project" by looking where it runs. `kennis gui` finds the
bundle where the person typed it and opens the address with
`bundle=<path>`; the guard's middleware keeps it as a cookie, and every
page reads it back here. An empty value is outside any project, so a tab
opened there does not keep an earlier project.

A cookie is shared by every tab of one origin, so the project is the one
the most recent `kennis gui` named, for every tab of this service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from starlette.requests import Request

from kennis.engine.context.bundle import is_bundle_dir

BUNDLE_COOKIE: Final = "kennis-bundle"
BUNDLE_PARAMETER: Final = "bundle"


def bundle_of(request: Request) -> Path | None:
    """The bundle this tab was opened for, or None outside a project.

    Only an absolute path to a directory carrying a bundle's manifest:
    anything else is no project, never a guess.
    """
    named = request.query_params.get(BUNDLE_PARAMETER)
    if named is None:
        named = request.cookies.get(BUNDLE_COOKIE)
    if not named:
        return None
    path = Path(named)
    return path if path.is_absolute() and is_bundle_dir(path) else None


__all__ = ["BUNDLE_COOKIE", "BUNDLE_PARAMETER", "bundle_of"]
