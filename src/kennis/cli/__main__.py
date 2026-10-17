"""The `kennis` command.

The group every subcommand attaches to, and the two options that belong to
every command because they are about output rather than about work:
`--quiet` and `--no-progress`. Both are applied to `display` once, here, so
no engine function ever receives a verbosity flag.

**A domain error becomes a message, never a traceback.** Every `KennisError`
carries the command that resolves it, and this is where that is turned into
the two lines a user sees. A traceback would be the engine's internals
printed at someone who asked a question.
"""

from __future__ import annotations

import logging

import click

from kennis import __version__
from kennis.cli import display
from kennis.cli.commands import (
    backup_group,
    config_group,
    context_group,
    corpus_group,
    gui_command,
    pack_group,
    read_command,
    remember_command,
    search_command,
    serve_command,
)
from kennis.cli.group import KennisGroup
from kennis.engine.errors import SettingsError
from kennis.engine.settings import load_settings
from kennis.logs import start_logging


def _logging_settings() -> dict[str, int]:
    """The configuration's `[logging]` section, as `start_logging` takes it.

    A configuration that will not load still gets a log, at the defaults:
    the log is how the reason gets read, and the command reports the
    failure itself when it loads the settings again.
    """
    try:
        section = load_settings().logging
    except SettingsError:
        return {}
    return {
        "level": logging.getLevelNamesMapping()[section.level.upper()],
        "max_bytes": section.max_bytes,
        "backup_count": section.backup_count,
    }


@click.group(cls=KennisGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="kennis")
@click.option("-q", "--quiet", is_flag=True, help="Print nothing but failures.")
@click.option(
    "--no-progress", is_flag=True, help="Suppress live progress bars, not the report."
)
@click.pass_context
def main(ctx: click.Context, *, quiet: bool, no_progress: bool) -> None:
    """A knowledge and memory system for people and AI agents."""
    display.set_verbosity(quiet=quiet, progress=not no_progress)
    # Always on, because the log is what you ask for when something went
    # wrong and it has to already exist by then.
    start_logging(**_logging_settings())
    logging.getLogger("kennis.cli").info("kennis %s", __version__)
    # Which command, with which parameters, is logged by `KennisCommand` -
    # after this callback, so the handler above already exists. Click 8.5
    # exposes no useful remainder at the group level, and each command
    # knowing its own parameters is the better record anyway.
    del ctx


main.add_command(corpus_group)
main.add_command(config_group)
main.add_command(backup_group)
main.add_command(context_group)
main.add_command(pack_group)
main.add_command(search_command)
main.add_command(read_command)
main.add_command(remember_command)
main.add_command(gui_command)
main.add_command(serve_command)


if __name__ == "__main__":
    main()
