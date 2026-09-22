"""The command and group classes every kennis command is built from.

Their own module rather than the entry point's, because the command modules
import them and the entry point imports the command modules - which through
`__main__` would be a cycle.
"""

from __future__ import annotations

import logging

import click

from kennis.cli import display
from kennis.engine.errors import KennisError
from kennis.logs import log_path


class KennisCommand(click.Command):
    """A command that records itself before it runs.

    Section 14's rule is that the log holds what the report leaves out, and
    the first thing it leaves out is what was asked for. Taken from click's
    own parse rather than from `sys.argv`, because a caller that invokes a
    command directly - a test, or the MCP server later - has an argv
    belonging to something else entirely.
    """

    def invoke(self, ctx: click.Context) -> object:
        logging.getLogger("kennis.cli").info(
            "%s %s",
            ctx.command_path,
            " ".join(f"{name}={value!r}" for name, value in sorted(ctx.params.items())),
        )
        return super().invoke(ctx)


class KennisGroup(click.Group):
    """A group that turns a domain error into a message and a resolution.

    Handled here rather than in the `run` wrapper so that every caller gets
    it - including `CliRunner`, which invokes the group directly. A handler
    only the console entry point installs is one the tests never exercise,
    which is how a traceback reaches a user despite a green suite.

    Its commands default to `KennisCommand`, so a command added later is
    logged without anyone remembering to ask for it.
    """

    command_class = KennisCommand

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except click.Abort as aborted:
            # Here rather than in the entry point, for the same reason the
            # handler below is: a command cancelled at a confirmation prompt
            # is cancelled whoever invoked it. click's own standalone mode
            # would print "Aborted!" and exit 1; `Cancelled` says it in
            # kennis's wording and exits 130, which is what a caller
            # checking `$?` in a loop expects of an interrupted command.
            raise display.Cancelled("nothing was changed") from aborted
        except KennisError as error:
            display.failure(str(error))
            for note in getattr(error, "__notes__", []):
                display.hint(note)
            display.hint(f"full detail in {log_path()}")
            raise SystemExit(1) from error
