"""The names of search groups for project context.

Pure functions over strings, kept apart from the modules that index and
search a bundle so that a client naming a group in its output imports
nothing of the engine's retrieval (#535).
"""

from __future__ import annotations

from typing import Final

CONTEXT_COLLECTION: Final = "context"


def project_group(project: str) -> str:
    """A search group for one project's notes when it is not the project
    the search was run from, whose group is plain `context` (14g)."""
    return f"{CONTEXT_COLLECTION}:{project}"


def project_of_group(name: str) -> str | None:
    """The project a `context:<project>` group is named for, else None."""
    prefix = f"{CONTEXT_COLLECTION}:"
    return name.removeprefix(prefix) if name.startswith(prefix) else None


def is_bundle_group(name: str) -> bool:
    """Whether a search group holds a project's own notes."""
    return name == CONTEXT_COLLECTION or project_of_group(name) is not None


__all__ = [
    "CONTEXT_COLLECTION",
    "is_bundle_group",
    "project_group",
    "project_of_group",
]
