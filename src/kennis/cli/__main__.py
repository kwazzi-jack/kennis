"""The `kennis` command.

Milestone 0 has no subcommands to offer. What exists here is the group the
later ones attach to, and the two options that belong to every command because
they are about output rather than about work: `--quiet` and `--no-progress`.
Both are applied to `display` once, at the group, so no engine function ever
receives a verbosity flag.
"""

from __future__ import annotations

import click

from kennis import __version__
from kennis.cli import display


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="kennis")
@click.option("-q", "--quiet", is_flag=True, help="Print nothing but failures.")
@click.option(
    "--no-progress", is_flag=True, help="Suppress live progress bars, not the report."
)
def main(*, quiet: bool, no_progress: bool) -> None:
    """A knowledge and memory system for people and AI agents."""
    display.set_verbosity(quiet=quiet, progress=not no_progress)


if __name__ == "__main__":
    main()
