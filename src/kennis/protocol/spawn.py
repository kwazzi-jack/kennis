"""Starting a process that belongs to nobody (14b).

Shared by the client, which starts the launcher, and the launcher, which
starts the service. Three null standard streams, because under `kennis
serve` the client's stdout is the MCP wire (#291). On POSIX a session of
its own, so a terminal closing does not end it; on Windows the creation
flags give it no console, so no window flashes open.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

# The launcher's status when the service neither held the corpus nor exited
# in time (`service/launch.py`); the client then goes on looking for it.
STILL_STARTING: Final = 75

# The status of a start asked to own a folder that is no corpus: the
# service's own when it is asked, and the client's and the launcher's
# before they start anything, since a process cannot start in a folder
# that does not exist.
NO_CORPUS: Final = 2


def holds_a_corpus(folder: Path) -> bool:
    return (folder / ".git").is_dir()


def service_command(corpus_root: Path) -> list[str]:
    """The service for `corpus_root`, which is started in that folder.

    `-P` because `-m` would otherwise put the working directory first on
    `sys.path`, and a file a person left in the corpus root would then be
    imported in place of a library.
    """
    return [sys.executable, "-P", "-m", "kennis.service", "--corpus", str(corpus_root)]


def spawned(command: list[str], *, cwd: Path) -> subprocess.Popen[bytes]:
    """`command` started in `cwd` with nothing inherited from this process.

    The directory is given rather than inherited, so nothing in the
    process can depend on where its starter happened to be (#508).
    """
    if sys.platform == "win32":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            cwd=cwd,
        )
    # `else` rather than falling through: mypy checking for Windows calls a
    # statement after the branch unreachable, and one inside the other arm
    # of a platform check it leaves alone.
    else:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            cwd=cwd,
        )


__all__ = [
    "NO_CORPUS",
    "STILL_STARTING",
    "holds_a_corpus",
    "service_command",
    "spawned",
]
