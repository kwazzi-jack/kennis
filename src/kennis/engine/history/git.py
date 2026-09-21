"""Running the `git` binary, under the external-process discipline.

kennis shells out to git rather than binding a library. Git is a system
requirement, checked once, with no fallback - a design where history is
optional needs a second implementation of index freshness for when git is
absent, and two implementations of one question drift apart.

**Every call gets a timeout and a closed stdin.** The timeout is the ordinary
rule for any external process. The closed stdin is specific to git: it will
block on a terminal prompt for credentials or open an editor, and a kennis
command that hangs with no output is the worst failure available. With stdin
closed those become failures, which a caller can report.

**A failure is a returned result, not an exception.** Git says a great many
things by exiting non-zero, most of which the caller wants to inspect rather
than propagate. The single exception is the binary being absent, which no
caller can proceed past, and which is therefore raised.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.errors import GitUnavailable

_BINARY: Final = "git"

# Generous for a local repository, and short enough that a wedged call is
# noticed rather than waited out. Nothing here talks to a network.
_TIMEOUT_SECONDS: Final = 30

# Who a corpus commit is by. Forced rather than inherited: these are kennis's
# own commits, recording what a command did, and attributing them to whichever
# person the machine happens to have configured would put a human's name on a
# machine's action. It also means `corpus init` works on a machine that has
# never configured git at all, which is otherwise a failure on the very first
# commit and a confusing one.
_AUTHOR_NAME: Final = "kennis"
_AUTHOR_EMAIL: Final = "kennis@localhost"


@dataclass(frozen=True, slots=True)
class GitResult:
    """What one git invocation did."""

    command: tuple[str, ...]
    status: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.status == 0

    def lines(self) -> list[str]:
        """Standard output as lines, without the empty tail.

        Almost every porcelain command kennis runs is read line by line, and
        the trailing newline would otherwise become an empty entry that every
        caller has to remember to drop.
        """
        return [line for line in self.stdout.splitlines() if line]


def git_binary() -> str:
    """The path to the git binary, or a refusal naming how to install it."""
    found = shutil.which(_BINARY)
    if found is None:
        raise GitUnavailable
    return found


def git(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: float = _TIMEOUT_SECONDS,
) -> GitResult:
    """Run one git command in `cwd` and return what it did."""
    command = (git_binary(), *arguments)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=_environment(),
        )
    except subprocess.TimeoutExpired:
        return GitResult(
            command=tuple(command),
            status=-1,
            stdout="",
            stderr=(
                f"git {' '.join(arguments)} timed out after {timeout}s and was "
                "cancelled"
            ),
        )
    return GitResult(
        command=tuple(command),
        status=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _environment() -> dict[str, str]:
    """The environment every git call runs in.

    Set in one place rather than at each call site, because each of these is
    a way for a kennis command to hang or to behave differently on one
    machine than another.
    """
    environment = dict(os.environ)
    environment.update(
        {
            # A prompt kennis cannot answer becomes a failure it can report.
            "GIT_TERMINAL_PROMPT": "0",
            # A pager would wait for a terminal that is not there.
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            # See `_AUTHOR_NAME`: machine commits, and no dependence on the
            # machine having an identity configured.
            "GIT_AUTHOR_NAME": _AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": _AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": _AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": _AUTHOR_EMAIL,
            # A global hook firing inside a corpus commit is a class of
            # surprise kennis could not diagnose and the user would not
            # expect, since they never ran git.
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return environment
