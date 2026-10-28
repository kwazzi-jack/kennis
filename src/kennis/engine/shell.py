"""One argument quoted so a printed command runs as printed on this platform.

The engine composes one kind of text a front end prints as it is - a
resolution, which is a command string - and a command naming an address or
a path has to quote it for the shell that will read it. `render/` quotes
its remedies with the same functions.
"""

from __future__ import annotations

import os
import shlex
import subprocess


def quoted_for_posix(argument: str) -> str:
    """One argument as a POSIX shell reads it."""
    return shlex.quote(argument)


def quoted_for_windows(argument: str) -> str:
    """One argument as cmd.exe and PowerShell both read it.

    `list2cmdline` double-quotes only when the argument needs it. A
    single-quoted path, which is what `shlex.quote` produces for any
    path containing a backslash, is not quoting to cmd.exe at all.
    """
    return subprocess.list2cmdline([argument])


def quoted_for_this_shell(argument: str) -> str:
    """One argument quoted so the remedy runs as printed on this platform."""
    if os.name == "nt":
        return quoted_for_windows(argument)
    return quoted_for_posix(argument)


__all__ = ["quoted_for_posix", "quoted_for_this_shell", "quoted_for_windows"]
