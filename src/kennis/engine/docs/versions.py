"""Which version of a project's documentation a page is (#489).

A page is filed at `docs/<project>/<version>/`. The version is read from the
address the site was added from, or named by the reader, and never invented:
a label kennis made up would sit beside every search hit looking like a
fact.

Each project has a *current* version, which a search uses unless it is told
otherwise. It is recorded in `docs/<project>/.current` - a dotfile, so the
walk that finds documents skips it, and inside the corpus, so it is history
like the pages are. With no record, or one naming a version not held, the
current version is the one fetched most recently.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import yaml

from kennis.engine.atomic import replace_file
from kennis.engine.corpus.layout import iter_documents
from kennis.engine.errors import InputError
from kennis.engine.frontmatter import split_frontmatter

CURRENT_FILENAME: Final = ".current"

# A release number - `2.12`, `v2.1.0`, `2.2.0rc1` - needs a dot or a leading
# `v`, so a page named `2.html` or a folder named `2023` is not taken for
# one.
_RELEASE: Final = re.compile(r"v\d+(\.\d+)*[a-z0-9.+-]*|\d+(\.\d+)+[a-z0-9.+-]*", re.I)
# The names hosts give a moving version instead of a number.
_CHANNELS: Final = frozenset({"latest", "stable", "dev", "main", "master", "nightly"})
# A version becomes a folder: a letter or digit first, so never `.` or `..`.
_FOLDER_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True, slots=True)
class ProjectVersions:
    """The versions of one project held, in order, and the current one."""

    held: tuple[str, ...]
    current: str


def version_in_address(address: str) -> str | None:
    """The version an address names, or None.

    The last segment of its path that is a release number or a channel
    name, so `/v1/api/2.3/` is `2.3`. A final segment that names a file is
    a page, not a version.
    """
    path = urlsplit(address).path
    segments = [segment for segment in path.split("/") if segment]
    if segments and not path.endswith("/") and "." in segments[-1]:
        last = segments[-1]
        if not _RELEASE.fullmatch(last):
            segments = segments[:-1]
    for segment in reversed(segments):
        if segment.lower() in _CHANNELS or _RELEASE.fullmatch(segment):
            return segment
    return None


def checked_version(version: str) -> str:
    """`version` if it can be a folder, otherwise a refusal naming the rule."""
    if not _FOLDER_NAME.fullmatch(version):
        raise InputError(
            f"'{version}' is not a usable version: it becomes a folder, so it "
            "must be letters, digits, '.', '-' and '_', starting with a letter "
            "or a digit"
        )
    return version


def current_version_file(docs_root: Path, project: str) -> Path:
    return docs_root / project / CURRENT_FILENAME


def make_current(docs_root: Path, project: str, version: str) -> None:
    replace_file(current_version_file(docs_root, project), f"{version}\n")


def project_versions(docs_root: Path) -> dict[str, ProjectVersions]:
    """Every project that has versions, with the versions held and the
    current one.

    A version is a folder directly inside its project. A project whose
    pages sit directly inside it has none and is left out.
    """
    found: dict[str, ProjectVersions] = {}
    if not docs_root.is_dir():
        return found
    for project_dir in sorted(docs_root.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        held = tuple(
            sorted(
                (
                    child.name
                    for child in project_dir.iterdir()
                    if child.is_dir()
                    and not child.name.startswith(".")
                    and any(iter_documents(child))
                ),
                key=version_order,
            )
        )
        if not held:
            continue
        found[project_dir.name] = ProjectVersions(
            held=held, current=_current_of(project_dir, held)
        )
    return found


# Every version of every project, as `kennis search --version all` says it.
EVERY_VERSION: Final = "all"


def excluded_versions(
    held: Mapping[str, ProjectVersions], chosen: Sequence[str]
) -> tuple[str, ...]:
    """The `project/version` groups a search leaves out, sorted.

    With nothing chosen, every version but each project's current one, so
    an ordinary search holds one copy of each page. `all` leaves out
    nothing. `project=version` searches that version of that project, and
    may be given more than once; a bare version applies to every project
    holding it. A project not named keeps its current version.

    A choice nothing holds is refused with what is held: a filter that
    matched nothing would answer "no passages" to a typing mistake.
    """
    if EVERY_VERSION in chosen:
        return ()
    wanted: dict[str, set[str]] = {}
    for choice in chosen:
        project, separator, version = choice.partition("=")
        if separator:
            versions = held.get(project)
            if versions is None or version not in versions.held:
                raise _unheld(choice, held)
            wanted.setdefault(project, set()).add(version)
            continue
        holders = [name for name, versions in held.items() if choice in versions.held]
        if not holders:
            raise _unheld(choice, held)
        for name in holders:
            wanted.setdefault(name, set()).add(choice)
    left_out = [
        f"{project}/{version}"
        for project, versions in held.items()
        for version in versions.held
        if version not in wanted.get(project, {versions.current})
    ]
    return tuple(sorted(left_out))


def chosen_or_default(
    held: Mapping[str, ProjectVersions], chosen: Sequence[str]
) -> tuple[str, ...]:
    """`chosen` as a search's address should carry it: empty when it
    searches exactly what the default does, so an ordinary search's
    address is what it was before there were versions. Repeats dropped,
    order kept. Raises as `excluded_versions` does.
    """
    unique = tuple(dict.fromkeys(choice for choice in chosen if choice))
    if not unique:
        return ()
    if excluded_versions(held, unique) == excluded_versions(held, ()):
        return ()
    return unique


def versions_holding(docs_root: Path, project: str, page: str) -> tuple[str, ...]:
    """Every version of `project` that holds `page`, in version order: the
    same page in the other versions, for a document page to link to."""
    project_dir = docs_root / project
    held = project_versions(docs_root).get(project)
    if held is None:
        return ()
    found: list[str] = []
    for version in held.held:
        for location in iter_documents(project_dir / version):
            try:
                mapping, _ = split_frontmatter(
                    location.md_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                continue
            docs = mapping.get("docs")
            if isinstance(docs, dict) and docs.get("page") == page:
                found.append(version)
                break
    return tuple(found)


def pages_of_version(docs_root: Path, project: str, version: str) -> int:
    """How many pages one version of a project holds, or a refusal naming
    the versions that are held: what removing it would remove, said before
    anything is removed."""
    held = project_versions(docs_root).get(project)
    if held is None or version not in held.held:
        raise InputError(
            f"no version '{version}' of '{project}' is held"
            + (f" - held are {', '.join(held.held)}" if held is not None else "")
        )
    return sum(1 for _ in iter_documents(docs_root / project / version))


def _unheld(choice: str, held: Mapping[str, ProjectVersions]) -> InputError:
    listing = "; ".join(
        f"{project}: {', '.join(versions.held)}" for project, versions in held.items()
    )
    return InputError(
        f"no documentation version '{choice}' is held"
        + (f" - held are {listing}" if listing else "")
    )


def _current_of(project_dir: Path, held: tuple[str, ...]) -> str:
    record = project_dir / CURRENT_FILENAME
    try:
        named = record.read_text(encoding="utf-8").strip()
    except OSError:
        named = ""
    if named in held:
        return named
    return max(held, key=lambda version: _newest_fetch(project_dir / version))


def _newest_fetch(version_dir: Path) -> str:
    """The latest `source.at` among a version's pages, as ISO text, which
    orders as time does; empty when none says."""
    newest = ""
    for location in iter_documents(version_dir):
        try:
            mapping, _ = split_frontmatter(location.md_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        source = mapping.get("source")
        at = source.get("at") if isinstance(source, dict) else None
        if at is not None and str(at) > newest:
            newest = str(at)
    return newest


def version_order(version: str) -> tuple[tuple[int, int | str], ...]:
    """Numbers as numbers, so `2.9` comes before `2.10`."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.findall(r"\d+|[^\d.]+", version)
    )


__all__ = [
    "CURRENT_FILENAME",
    "EVERY_VERSION",
    "ProjectVersions",
    "checked_version",
    "chosen_or_default",
    "current_version_file",
    "excluded_versions",
    "make_current",
    "pages_of_version",
    "project_versions",
    "version_in_address",
    "version_order",
    "versions_holding",
]
