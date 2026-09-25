"""`kennis context`: the knowledge that belongs to this project.

The corpus is machine-global; a bundle is a `.context/` directory at the
root of a workspace, committed with it. Every command here starts by
deciding which directory that is, which is `find_bundle`'s job and the one
thing `design.md` left unspecified - concern #225.
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.engine.context import (
    LANDING_FILENAME,
    BundleCreated,
    find_bundle,
    init_bundle,
    workspace_root,
)
from kennis.engine.errors import ContextNotFound


@click.group(name="context", cls=KennisGroup)
def context_group() -> None:
    """The knowledge bundle for the project you are standing in."""


@context_group.command(name="init", cls=KennisCommand)
@click.option(
    "--here",
    is_flag=True,
    help="Create it in the working directory instead of the workspace root.",
)
def init_command(here: bool) -> None:
    """Create this project's `.context/` bundle.

    **Where it goes is not always where you are.** A bundle belongs at the
    root of a workspace, so this walks up to the nearest `.git` and creates
    it there; running the command three directories deep should not bury it
    there. The path is reported for that reason. `--here` overrides it.

    Re-runnable, and converging rather than merely not-failing: a scaffold
    file that was deleted is written again, and anything you added is left
    alone.
    """
    created = init_bundle(Path.cwd() if here else workspace_root())
    _report_init(created)


def _report_init(created: BundleCreated) -> None:
    """What `init` did, in the three shapes it can take.

    `guidance` rather than `note` for the two informational lines: `note`
    prints `warning:`, and a bundle that was already complete is not
    something going wrong.
    """
    if created.created:
        display.operation("Created", f"context bundle at {created.path}")
        # Not `next_step`: rule 4.4 says a printed command runs as printed,
        # and the command a new bundle wants next - `remember --context` -
        # does not exist yet. The landing file does, and reading it first is
        # what it asks for anyway.
        # Relative to the bundle, which the line above just named in full.
        # An absolute path here is long enough to be wrapped by the prose
        # style that prints it, and a wrapped path cannot be copied.
        display.guidance(f"start at {created.path.name}/{LANDING_FILENAME}")
        return
    display.operation("Found", f"context bundle at {created.path}")
    if created.restored:
        # The markers say what happened; a count beneath them would repeat
        # what the reader just read.
        display.details("+", list(created.restored))
        return
    display.guidance("already complete, nothing to put back")


def require_bundle() -> Path:
    """The bundle governing the working directory, or the error naming the
    command that makes one.

    Every context command but `init` starts here.
    """
    bundle = find_bundle()
    if bundle is None:
        raise ContextNotFound
    return bundle


__all__ = ["context_group", "require_bundle"]
