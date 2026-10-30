"""The command and group classes every kennis command is built from.

Their own module rather than the entry point's, because the command modules
import them and the entry point imports the command modules - which through
`__main__` would be a cycle.
"""

from __future__ import annotations

import logging

import click

from kennis.cli import display
from kennis.client.calls import JobDetached
from kennis.client.process import tell_of_recovery
from kennis.engine.errors import KennisError, TaskStopped
from kennis.logs import log_path
from kennis.render.paths import from_home
from kennis.render.words import put_back_at_start


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
        tell_of_recovery(
            lambda operation: display.warning(put_back_at_start(operation))
        )
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
        except TaskStopped as stopped:
            # Asked for, so not a failure: worded and exited as a cancelled
            # prompt is, which the shell reads as an interrupted command.
            raise display.Cancelled(str(stopped)) from stopped
        except JobDetached as detached:
            # Ctrl-C a second time, while the task was being cancelled: the
            # watching stopped, and the cancel already asked stands. Not a
            # failure, so not `failure`;
            # 130, as any interrupted command exits, because the caller's
            # command did not run to its end here.
            display.note(detached.message)
            display.next_step(f"kennis service watch {detached.job}")
            raise SystemExit(130) from detached
        except KennisError as error:
            display.failure(str(error))
            for note in getattr(error, "__notes__", []):
                display.remedy(note)
            # Not a command, so shown from `~` as prose is.
            display.remedy(f"full detail in {from_home(str(log_path()))}")
            raise SystemExit(1) from error
