"""The statuses a kennis command exits with, by name (Brian, 2026-11-27).

One definition, because a caller checking `$?` reads these as a contract
and the literals they replace were scattered through the command line.
`docs/reference/cli.md` lists them for a reader, and a test checks the
two agree.
"""

from __future__ import annotations

from enum import IntEnum


class ExitStatus(IntEnum):
    """What a command's exit status says about the run."""

    # The command did what it was asked.
    DONE = 0
    # It refused, or something it was asked to do failed: a refused add,
    # a paper a sync could not fetch or convert, a pack that does not
    # validate. The report above the exit says which.
    FAILED = 1
    # click's own, for an option or argument it could not parse. Named so
    # the table is complete; kennis never raises it itself.
    USAGE = 2
    # A sync did everything it could and some pack papers still need the
    # reader's own copy: skipped at the prompt, or never asked because no
    # terminal was there to ask on.
    INCOMPLETE = 3
    # Stopped by the person: Ctrl-C, a cancelled prompt, a stopped task.
    # 128 + SIGINT, which is what a shell loop expects of an interrupt.
    INTERRUPTED = 130


__all__ = ["ExitStatus"]
