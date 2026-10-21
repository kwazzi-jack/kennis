"""The machine's projects: every bundle kennis has touched (14g, #512).

A bundle belongs to one project and lives in that project's repository,
so nothing about one says where the others are. This list does, for the
window that shows every project and the search that covers them. It
records paths and nothing else: no document moves between projects.

**Under the state directory, never in the corpus.** The corpus is
committed and synced, and where a person keeps their repositories is a
fact about this machine.

**A project is recorded where kennis touches its bundle** - making it,
remembering into it, indexing it, syncing it, searching it - and by
`kennis context add`. Recording a project already listed writes nothing,
so a search pays one read of a small file. A folder that has gone is
listed as missing until it is forgotten, never dropped silently: a
project on an unmounted disk is not a project that was deleted.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from filelock import FileLock

from kennis.engine.atomic import replace_file
from kennis.engine.context.bundle import BUNDLE_DIRNAME, is_bundle_dir
from kennis.engine.errors import (
    ContextNotFound,
    ProjectListUnreadable,
    ProjectNotKnown,
)
from kennis.engine.settings import state_dir

PROJECTS_FILENAME: Final = "projects.json"
_SCHEMA_VERSION: Final = 1
# The list is a few hundred bytes and is written in a moment, so a second
# writer - another corpus's service, or a command - waits rather than being
# refused, as the corpus lock does (14e). Bounded, because nothing here
# should take longer.
_LOCK_SECONDS: Final = 10.0

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Project:
    """A known project: what it is called here, its bundle, and whether the
    bundle is still there."""

    name: str
    bundle: Path
    present: bool


def projects_path() -> Path:
    return state_dir() / PROJECTS_FILENAME


def known_projects() -> tuple[Project, ...]:
    """Every listed project, by name."""
    bundles = _read(projects_path())
    names = _names_for([bundle.parent for bundle in bundles])
    return tuple(
        sorted(
            (
                Project(
                    name=names[bundle.parent],
                    bundle=bundle,
                    present=is_bundle_dir(bundle),
                )
                for bundle in bundles
            ),
            key=lambda project: project.name,
        )
    )


def record_project(bundle: Path) -> bool:
    """List `bundle`'s project. True when this added it, False when it was
    listed already or `bundle` is no bundle."""
    if not is_bundle_dir(bundle):
        return False
    resolved = bundle.resolve()
    path = projects_path()
    if resolved in _read(path):
        return False
    with _locked(path):
        listed = _read(path)
        if resolved in listed:
            return False
        _write(path, [*listed, resolved])
    return True


def note_project(bundle: Path) -> None:
    """`record_project` for the places that touch a bundle on their way to
    something else: a list that cannot be read is logged, never raised,
    because a note or a search that failed over it would fail for a reason
    the person did not ask about."""
    try:
        record_project(bundle)
    except ProjectListUnreadable as error:
        _logger.warning("%s", error)


def add_project(folder: Path) -> Project:
    """List the project whose bundle is `folder` or `folder/.context`."""
    bundle = folder if is_bundle_dir(folder) else folder / BUNDLE_DIRNAME
    if not is_bundle_dir(bundle):
        raise ContextNotFound(f"{folder} holds no context bundle")
    record_project(bundle)
    resolved = bundle.resolve()
    return next(project for project in known_projects() if project.bundle == resolved)


def project_named(name: str) -> Project:
    """The known project called `name`; refused, naming the list, when
    there is none."""
    found = next((one for one in known_projects() if one.name == name), None)
    if found is None:
        raise ProjectNotKnown(f"no project is called {name!r}")
    return found


def present_bundles() -> tuple[Path, ...]:
    """Every known project's bundle that is where the list says, which is
    what a search across projects reads. Never raises over the list: a
    search that failed over it would fail for a reason not asked about."""
    try:
        return tuple(one.bundle for one in known_projects() if one.present)
    except ProjectListUnreadable as error:
        _logger.warning("%s", error)
        return ()


def project_names(bundles: Sequence[Path]) -> dict[Path, str]:
    """Each bundle's project name as the list gives it, keyed by the bundle
    as given; a bundle the list does not hold is named by its folder."""
    try:
        known = {one.bundle: one.name for one in known_projects()}
    except ProjectListUnreadable:
        known = {}
    return {
        bundle: known.get(bundle.resolve(), bundle.resolve().parent.name)
        for bundle in bundles
    }


def forget_project(name: str) -> Project:
    """Take the project called `name` off the list. Its files are untouched."""
    path = projects_path()
    with _locked(path):
        projects = known_projects()
        found = next((project for project in projects if project.name == name), None)
        if found is None:
            raise ProjectNotKnown(f"no project is called {name!r}")
        _write(path, [project.bundle for project in projects if project != found])
    return found


def _names_for(folders: list[Path]) -> dict[Path, str]:
    """Each project folder's name, lengthened by its parents only where two
    would otherwise share one."""
    depth = dict.fromkeys(folders, 1)
    while True:
        names = {folder: "/".join(folder.parts[-depth[folder] :]) for folder in folders}
        counts: dict[str, int] = {}
        for name in names.values():
            counts[name] = counts.get(name, 0) + 1
        clashing = [
            folder
            for folder in folders
            if counts[names[folder]] > 1 and depth[folder] < len(folder.parts)
        ]
        if not clashing:
            return names
        for folder in clashing:
            depth[folder] += 1


def _read(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return [Path(entry["bundle"]) for entry in document["projects"]]
    except (ValueError, KeyError, TypeError) as error:
        raise ProjectListUnreadable(
            f"the list of projects at {path} could not be read ({error})"
        ) from error


def _write(path: Path, bundles: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": _SCHEMA_VERSION,
        "written_at": datetime.now(UTC).isoformat(),
        "projects": [{"bundle": str(bundle)} for bundle in bundles],
    }
    replace_file(path, json.dumps(document, indent=2) + "\n")


def _locked(path: Path) -> FileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_name(f".{path.name}.lock")), timeout=_LOCK_SECONDS)


__all__ = [
    "PROJECTS_FILENAME",
    "Project",
    "add_project",
    "forget_project",
    "known_projects",
    "note_project",
    "present_bundles",
    "project_named",
    "project_names",
    "projects_path",
    "record_project",
]
