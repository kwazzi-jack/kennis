"""The `.context/` bundle: finding the one that governs a directory, and making one.

A bundle is knowledge that belongs to **one project** rather than to the
machine. It is a real directory at the root of a workspace, holding markdown
the user writes, committed with the project - so a fresh clone carries the
project's knowledge with it.

**The walk keys on the manifest, not on the directory.** A `.context/` with
no `bundle.json` is not a bundle: a half-made or hand-created one would
otherwise capture the walk and make the real bundle above it unreachable.
boepie learned this and kennis takes it. Concern #227.

**It walks to the filesystem root, not to `$HOME`.** A workspace inside a
home directory is ordinary, and stopping there would fail it.

Nothing here raises when a bundle is absent. "No bundle anywhere" and "a
bundle with no index" have different fixes, so `find_bundle` returns None
and the caller names the one that applies.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from kennis import __version__
from kennis.engine._atomic import replace_file

BUNDLE_DIRNAME: Final = ".context"
MANIFEST_FILENAME: Final = "bundle.json"
LANDING_FILENAME: Final = "LANDING.md"
SKELETON_FILENAME: Final = ".skeleton.md"
GITIGNORE_FILENAME: Final = ".gitignore"
INDEX_DIRNAME: Final = ".index"

SCHEMA_VERSION: Final = 1

_OVERRIDE_VARIABLE: Final = "KENNIS_CONTEXT_DIR"
_GIT_DIRNAME: Final = ".git"


@dataclass(frozen=True, slots=True)
class BundleCreated:
    """Where a bundle is, and whether this call is what made it.

    `created` distinguishes the first run from a re-run. `restored` names
    what a re-run had to put back, which is not nothing: a bundle missing
    its landing file is a bundle an agent cannot navigate.
    """

    path: Path
    created: bool
    restored: tuple[str, ...] = ()


def bundle_override() -> Path | None:
    """The bundle named by the environment, if any, before any walking."""
    named = os.environ.get(_OVERRIDE_VARIABLE)
    return Path(named).expanduser().resolve() if named else None


def is_bundle_dir(path: Path) -> bool:
    """Whether `path` is a bundle, which means carrying a manifest."""
    return (path / MANIFEST_FILENAME).is_file()


def find_bundle(start: Path | None = None) -> Path | None:
    """The bundle governing `start`, or None.

    The working directory is read **at call time** rather than at import:
    a long-lived server's working directory is wherever its client launched
    it, and a project's bundle may be created after the server starts.

    The override is honoured before the walk but is **still manifest-checked**,
    so a mistyped one fails as "no bundle" rather than silently serving a
    different project's knowledge.
    """
    override = bundle_override()
    if override is not None:
        return override if is_bundle_dir(override) else None

    here = (start if start is not None else Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / BUNDLE_DIRNAME
        if is_bundle_dir(candidate):
            return candidate
    return None


def workspace_root(start: Path | None = None) -> Path:
    """Where a new bundle belongs: the workspace's root, not the cwd.

    The nearest ancestor holding a `.git`, else `start` itself. Running
    `kennis context init` three directories into a repository should put the
    bundle at the top of it rather than burying it where the command
    happened to be run - which is why the command reports the path it chose.
    """
    here = (start if start is not None else Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / _GIT_DIRNAME).exists():
            return directory
    return here


def index_root_for(bundle: Path) -> Path:
    """Where a bundle's own index lives.

    Inside the bundle, so it is committed with the project and a fresh
    clone has working search with no setup - design section 19, which
    deliberately reverses boepie's decision to ignore it.
    """
    return bundle / INDEX_DIRNAME


def init_bundle(root: Path) -> BundleCreated:
    """Create the bundle under `root`, or fill in what is missing from one.

    Re-runnable, and converging rather than merely not-failing: a scaffold
    file that was deleted is written again, and anything the user added is
    left alone. Nothing here is destructive, so it takes no lock and needs
    no corpus.
    """
    bundle = root / BUNDLE_DIRNAME
    existed = is_bundle_dir(bundle)
    bundle.mkdir(parents=True, exist_ok=True)

    restored: list[str] = []
    for name, content in (
        (MANIFEST_FILENAME, _manifest()),
        (LANDING_FILENAME, _landing()),
        (SKELETON_FILENAME, _skeleton()),
        (GITIGNORE_FILENAME, _gitignore()),
    ):
        path = bundle / name
        if path.exists():
            continue
        replace_file(path, content)
        if existed:
            restored.append(name)
    return BundleCreated(path=bundle, created=not existed, restored=tuple(restored))


def _gitignore() -> str:
    """Keep the index out of the user's repository.

    **The index is local to one machine and one configuration.** It is
    derived from the documents beside it, it is rebuilt in milliseconds, and
    what it was built with - the chunk parameters, the embedding model if
    there is one - is a per-person setting. Committing it would put one
    person's configuration in everyone's working tree, so a clone rebuilds
    with its own.

    Inside the bundle rather than in the project's root `.gitignore`: that
    file is the user's, kennis does not edit files it does not own, and a
    self-contained rule travels with the directory it governs.
    """
    return """# The search index is derived, rebuilt in milliseconds, and specific to
# whoever built it - their chunk settings, and their embedding model if they
# configured one. Run `kennis context index` after cloning.
.index/
"""


def _manifest() -> str:
    """The marker the walk keys on.

    It says almost nothing today. Packs extend it to which packs, which
    versions, applied when (design section 10); its job now is to exist, so
    that a directory named `.context` is not mistaken for a bundle.
    """
    return (
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "created_by": f"kennis {__version__}",
            },
            indent=2,
        )
        + "\n"
    )


def _landing() -> str:
    """The entry point, written for an agent rather than for a browser.

    boepie's `index.md` is the model - read this first and jump, a table of
    question-shape to destination, a layout list - but not the content:
    boepie's is about stimela and kennis knows nothing about any subject. So
    this ships the convention and leaves the categories to whoever fills the
    bundle in.
    """
    return """# Project knowledge

Read this file first, then go straight to the file that answers your
question. Do not browse the whole tree.

## What is here

This directory holds knowledge specific to **this project**: conventions,
decisions, and anything a newcomer would otherwise have to be told. It is
committed with the repository, so it travels with a clone.

It is not the place for anything that changes faster than the repository
does, and not a cache of documentation that lives elsewhere.

## Layout

Nothing below is fixed. Make the directories this project needs and name
them after the questions they answer, nesting as deep as is useful:

    .context/
      LANDING.md          this file - keep the table below current
      .skeleton.md        the template for a file at this level
      conventions/        for example
        .skeleton.md      each directory may carry its own
        naming.md

| Question | Where to look |
|---|---|
| (add a row when you add a directory) | |

## Writing a file

    kennis remember --context "what you want kept"

That writes one file here, with the frontmatter filled in. `--title` names
it and `--group` puts it in a subdirectory, which is created if it is not
there yet.

By hand instead: copy `.skeleton.md`. Every file carries `title`,
`description` and `owner` in its frontmatter.

`owner: user` means you wrote it and nothing will overwrite it.

## Two conventions worth knowing

**A dot-prefixed file is never indexed or searched.** That is why the
templates are `.skeleton.md` - a template matches every query about its own
section and answers none of them. Rename any file to `.name.md` to keep it
out of search without deleting it.

**`LANDING.md` is not indexed either.** It is a map, not an answer, and you
are reading it first anyway.

## Searching

    kennis search "your question" --collection context

Hits are file paths. Open them with your own tools - there is no
`kennis read` for a bundle file, because it is a file in this repository
rather than a document kennis owns.
"""


def _skeleton() -> str:
    """The template a bundle file is copied from.

    Dotted, so it is excluded from the index by the same rule that excludes
    `.index/` - one mechanism rather than boepie's hardcoded name list
    beside a dot rule. Concern #227.
    """
    return """---
title: The one-line name of this file
description: One sentence saying what question this file answers.
owner: user
---

# The one-line name of this file

What this is, why it matters in this project, and the smallest example that
makes it concrete.

Delete the sections that do not apply. This file is a starting point, not a
form.
"""


__all__ = [
    "BUNDLE_DIRNAME",
    "INDEX_DIRNAME",
    "LANDING_FILENAME",
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "SKELETON_FILENAME",
    "BundleCreated",
    "bundle_override",
    "find_bundle",
    "index_root_for",
    "init_bundle",
    "is_bundle_dir",
    "workspace_root",
]
