"""Deleting a project's context bundle, which kennis cannot undo (2026-11-04).

Forgetting a project takes it off the machine's list and leaves its folder;
deleting removes the `.context/` folder too and then forgets it. The bundle
lives in the person's own repository, which kennis keeps no history of, so
what was committed there comes back through git and nothing else does.
Every front end asks first, naming the folder and how many files go.

The derived index, `.context/.index/`, is removed with the rest and not
counted: it is rebuilt from the documents and is not the person's writing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kennis.engine.atomic import remove_tree
from kennis.engine.context.bundle import BUNDLE_DIRNAME, INDEX_DIRNAME, is_bundle_dir
from kennis.engine.context.projects import Project, forget_project, project_named
from kennis.engine.errors import BundleNotDeletable, ContextNotFound


@dataclass(frozen=True, slots=True)
class BundleDeletion:
    """The project whose bundle goes, or went, and how many of its files
    outside the index."""

    project: Project
    files: int


def what_deleting_removes(name: str) -> BundleDeletion:
    """What `delete_project(name)` would remove, refused as it would be."""
    project = _deletable(name)
    return BundleDeletion(project=project, files=_files_in(project.bundle))


def delete_project(name: str) -> BundleDeletion:
    """Remove the project's bundle, read-only files included, then take the
    project off the list. A removal that fails leaves it listed, so the
    list still says where what is left of it is."""
    project = _deletable(name)
    files = _files_in(project.bundle)
    remove_tree(project.bundle)
    forget_project(name)
    return BundleDeletion(project=project, files=files)


def _deletable(name: str) -> Project:
    project = project_named(name)
    if not project.present:
        raise ContextNotFound(
            f"{name}'s bundle is not at {project.bundle}",
            resolution=f"kennis context forget {name}",
        )
    # Both, because each alone can be true of a folder that is not one:
    # `kennis context add` accepts a bundle under any name, and a folder
    # called `.context` need not be kennis's.
    if project.bundle.name != BUNDLE_DIRNAME or not is_bundle_dir(project.bundle):
        raise BundleNotDeletable(
            f"{project.bundle} is not a {BUNDLE_DIRNAME} folder holding a bundle",
            resolution=f"kennis context forget {name}",
        )
    return project


def _files_in(bundle: Path) -> int:
    return sum(
        1
        for path in bundle.rglob("*")
        if path.is_file() and INDEX_DIRNAME not in path.relative_to(bundle).parts
    )


__all__ = ["BundleDeletion", "delete_project", "what_deleting_removes"]
