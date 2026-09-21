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
import sys

import click

from kennis import __version__
from kennis.cli import display
from kennis.cli.commands import corpus_group
from kennis.cli.group import KennisGroup
from kennis.logs import start_logging


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
    start_logging()
    logging.getLogger("kennis.cli").info("kennis %s", __version__)
    # Which command, with which parameters, is logged by `KennisCommand` -
    # after this callback, so the handler above already exists. Click 8.5
    # exposes no useful remainder at the group level, and each command
    # knowing its own parameters is the better record anyway.
    del ctx


main.add_command(corpus_group)


def run() -> int:
    """The console entry point.

    Wraps `main` so a `KennisError` reaches the user as its own message and
    its own resolution, with the log named - which is what makes the log
    discoverable without a verb for it.
    """
    try:
        main.main(standalone_mode=False)
    except SystemExit as exiting:
        return int(exiting.code or 0)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort:
        display.failure("cancelled")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(run())
