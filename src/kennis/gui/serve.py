"""Running the interface: a server on a thread, a browser tab to read it.

**One process, not a service.** The server imports the engine directly,
as the other two front ends do, and lives until the person quits from
the page or presses Ctrl-C. A long-running service that front ends
connect to is deferred by the plan, and is the arrangement section 20's
"no front end is privileged" rule is easiest to violate by accident.

**A tab in the person's own browser, always** (#420). A native window
was tried in milestone 9 through `pywebview` and removed: it was an
optional dependency with a system requirement on Linux, a second
browser engine to test against, and its one capability a tab lacks - a
native file chooser - lists the wrong machine whenever kennis runs
remotely behind `ssh -L`.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from typing import Final, Protocol

import uvicorn

from kennis.gui.app import build_app, new_token
from kennis.gui.jobs import Jobs

# Loopback, spelled out. Not `localhost`, which resolves through the
# host file and can be made to mean something else, and never `0.0.0.0`,
# which would put a personal corpus on the network.
HOST: Final = "127.0.0.1"

# The kernel picks. A fixed port collides with whatever else a developer
# has on 8000, and - worse - makes the interface predictable to find for
# anything else running on a shared machine.
ANY_PORT: Final = 0


def _say_nothing(kind: str) -> None:
    """The default for `on_busy`: a caller that says nothing."""


def run(
    on_ready: Callable[[str], None],
    *,
    open_browser: bool = True,
    on_busy: Callable[[str], None] = _say_nothing,
) -> None:
    """Serve until the page asks to quit or the user interrupts.

    `on_ready` is handed the address **before** this blocks, and that
    ordering is the whole reason it is a callback rather than a return
    value: the call blocks for as long as the interface is open, so an
    address returned at the end would reach the user only once the
    interface had shut down - and `webbrowser.open` may silently fail,
    so that address is the only way in that is certain.

    `open_browser=False` opens nothing. Over `ssh -L` on a machine with
    no display, `webbrowser` does not fail: with `TERM` set it finds
    `www-browser`, `lynx` or `w3m` and runs a text browser in the
    terminal kennis is printing to.

    This module is not a front end's voice, so it hands the address
    over and the command decides what is said about it - and the same
    for `on_busy`, handed the running job's kind when a Ctrl-C arrives
    during it (#422).
    """
    token = new_token()
    quitting = threading.Event()
    app = build_app(token, on_quit=quitting.set)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=ANY_PORT,
            log_level="warning",
            # The access log would narrate every request to a terminal
            # the user is not reading, and a token in a query string
            # would be in it.
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True, name="kennis-gui")
    thread.start()
    url = f"http://{HOST}:{_port_of(server)}/?token={token}"
    on_ready(url)

    try:
        if open_browser:
            _open_quietly(url)
        _wait_for_quit(quitting, app.state.jobs, on_busy)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _open_quietly(url: str) -> None:
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


def _port_of(server: uvicorn.Server, timeout: float = 10.0) -> int:
    """The port the kernel gave, once the socket exists.

    Polled rather than pre-bound because uvicorn binds inside its own
    `run`, and guessing a free port and hoping it is still free is the
    race this avoids.
    """
    deadline = time.monotonic() + timeout
    idle = threading.Event()
    while time.monotonic() < deadline:
        if server.started and server.servers and server.servers[0].sockets:
            return int(server.servers[0].sockets[0].getsockname()[1])
        # An `Event` that is never set, waited on briefly: a sleep that
        # does not spin and does not need a second import.
        idle.wait(0.02)
    raise RuntimeError("the interface did not start listening")


class _Waitable(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


def _wait_for_quit(
    quitting: _Waitable, jobs: Jobs, on_busy: Callable[[str], None]
) -> None:
    """Block until the page asks to quit, or until Ctrl-C.

    Closing a tab does not end this process - the server cannot tell a
    closed tab from a reader who has gone to make tea - so one of these
    two has to.

    **A Ctrl-C during a job is asked twice** (#422). Quit refuses while
    a job runs, because the job is a daemon thread that may be inside
    the corpus lock or between writing a document and committing it;
    the first Ctrl-C says so and keeps serving, and a second ends the
    process wherever the job is, as the reader has then been told.
    """
    try:
        quitting.wait()
        return
    except KeyboardInterrupt:
        running = jobs.running()
        if running is None:
            return
        on_busy(running.kind)
    try:
        quitting.wait()
    except KeyboardInterrupt:
        return


__all__ = ["ANY_PORT", "HOST", "run"]
