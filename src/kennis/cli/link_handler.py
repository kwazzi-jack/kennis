"""What the desktop runs for a clicked `kennis://` link (#8).

`python -m kennis.cli.link_handler <link>` is `kennis open <link>`, run
where nobody reads a terminal. On Windows it runs under `pythonw.exe`, so no
console window opens, and there the standard streams are absent: anything
written to them would raise. They are pointed at the null device first. A
failure is then reported only in kennis's log, as every command's is.
"""

from __future__ import annotations

import io
import os
import sys


def give_absent_streams_somewhere() -> None:
    """Point a missing standard stream, and its descriptor, at the null
    device; a stream that exists is left as it is."""
    null = os.open(os.devnull, os.O_RDWR)
    for descriptor in (0, 1, 2):
        try:
            os.fstat(descriptor)
        except OSError:
            os.dup2(null, descriptor)
    os.close(null)
    # Each wraps its descriptor, which now exists, for the rest of the
    # process's life: there is no later point at which to close it.
    if sys.stdin is None:
        sys.stdin = io.TextIOWrapper(io.FileIO(0, "r", closefd=False))
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(io.FileIO(1, "w", closefd=False))
    if sys.stderr is None:
        sys.stderr = io.TextIOWrapper(io.FileIO(2, "w", closefd=False))


def handle(arguments: list[str]) -> None:
    """Open the link in `arguments`, as `kennis open` would."""
    give_absent_streams_somewhere()
    from kennis.cli.__main__ import main

    main(["open", *arguments])


if __name__ == "__main__":
    handle(sys.argv[1:])
