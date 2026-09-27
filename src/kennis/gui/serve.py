"""Running the interface: a server on a thread, a window on the main one.

**One process, not a service.** The server imports the engine directly,
as the other two front ends do, and lives exactly as long as the window
does. A long-running service that front ends connect to is deferred by
the plan, and is the arrangement section 20's "no front end is
privileged" rule is easiest to violate by accident.

**The window is optional and its absence is not an error.** `pywebview`
resolves its backend inside `start()` - WebView2 on Windows, WKWebView
on macOS, WebKitGTK on Linux - and on Linux nothing installs one by
default. So the window is attempted and a browser tab is the fallback.
Measured rather than assumed: on this machine `create_window` succeeds
and `start()` is where the absence surfaces, as an `AttributeError`
from pywebview's own internals.
"""

from __future__ import annotations

import threading
import time
import webbrowser
from collections.abc import Callable
from typing import Final

import uvicorn

from kennis.gui.app import build_app, new_token

# Loopback, spelled out. Not `localhost`, which resolves through the
# host file and can be made to mean something else, and never `0.0.0.0`,
# which would put a personal corpus on the network.
HOST: Final = "127.0.0.1"

# The kernel picks. A fixed port collides with whatever else a developer
# has on 8000, and - worse - makes the interface predictable to find for
# anything else running on a shared machine.
ANY_PORT: Final = 0

_WINDOW_TITLE: Final = "kennis"


def run(on_ready: Callable[[str], None], *, browser_only: bool = False) -> None:
    """Serve until the window closes or the user interrupts.

    `on_ready` is handed the address **before** this blocks, and that
    ordering is the whole reason it is a callback rather than a return
    value: the call blocks for as long as the interface is open, so an
    address returned at the end would reach the user only once the
    interface had shut down - and in browser mode, where
    `webbrowser.open` may silently fail, that address is the only way
    back in.

    This module is not a front end's voice, so it hands the address
    over and the command decides what is said about it.
    """
    token = new_token()
    server = uvicorn.Server(
        uvicorn.Config(
            build_app(token),
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
        if browser_only or not _shown_in_a_window(url):
            webbrowser.open(url)
            _wait_until_interrupted()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


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


def _shown_in_a_window(url: str) -> bool:
    """True if a native window was opened and has now been closed.

    **A broad `except` on purpose**, which is usually a smell. pywebview
    reports a missing backend from inside its own internals - on this
    machine an `AttributeError` about `NoneType`, which is not a
    contract and will differ by version and platform. The three
    platforms fail three ways and none of them is documented, so
    catching narrowly here would mean catching whatever this machine
    happens to raise and falling over on the other two.
    """
    try:
        import webview
    except ImportError:
        return False
    try:
        webview.create_window(_WINDOW_TITLE, url)
        webview.start()
    except Exception:
        return False
    return True


def _wait_until_interrupted() -> None:
    """Block until Ctrl-C, for the browser case.

    There is no window to close, so something has to hold the process
    open; an `Event` that is never set is the cheapest thing that
    blocks without spinning.
    """
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        return


__all__ = ["ANY_PORT", "HOST", "run"]
