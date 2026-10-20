"""Opening the person's own browser on the window (#420).

A tab in their browser, always: a native window was tried in milestone 9
and removed, and a browser tab is what works behind `ssh -L` too.
"""

from __future__ import annotations

import os
import sys
import webbrowser


def open_quietly(url: str) -> None:
    """Open the person's browser without lending it kennis's terminal.

    `webbrowser` starts the browser with no redirection, so it inherits
    descriptors 1 and 2, and Brave wrote "Opening in existing browser
    session." and a zygote ERROR under kennis's address. Both are
    pointed at the null device for this call only: a child started now
    keeps it for its whole life, and kennis's own output is restored when
    the call returns (#319, #453). The address was printed before this,
    so a browser that fails to open still leaves a way in.
    """
    for stream in (sys.stdout, sys.stderr):
        stream.flush()
    saved = {descriptor: os.dup(descriptor) for descriptor in (1, 2)}
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        for descriptor in saved:
            os.dup2(null, descriptor)
        webbrowser.open(url)
    finally:
        for descriptor, original in saved.items():
            os.dup2(original, descriptor)
            os.close(original)
        os.close(null)


__all__ = ["open_quietly"]
