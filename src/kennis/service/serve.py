"""Running the service: one process per corpus, until it is idle or told (14b).

Started by a client that found none (`client/process.py`), detached, with
no standard streams - under `kennis serve` the client's stdout is the MCP
wire, and nothing the service does may reach it. What it would have said
goes to the log.

**One owner.** The corpus's service lock is taken before anything binds,
so of two services started at once for one corpus the second finds it held
and exits at once; its client then finds the first through the record.

**Three ways to stop**, each refused while a job is queued or running, for
the reason the window's Quit is: a `POST /api/1/stop` (`kennis service
stop`), `SIGTERM` where the platform sends one, and the idle timer.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

import uvicorn
from filelock import Timeout

from kennis import __version__
from kennis.engine.settings import load_settings
from kennis.engine.staging import recover
from kennis.gui.app import new_token
from kennis.logs import start_logging
from kennis.protocol.record import (
    ServiceRecord,
    owner_lock,
    remove_record,
    write_record,
)
from kennis.protocol.spawn import NO_CORPUS, holds_a_corpus
from kennis.publishing import exclusively
from kennis.service.app import build_service_app
from kennis.service.idle import IdleTimer

# Loopback, spelled out. Not `localhost`, which resolves through the host
# file and can be made to mean something else, and never `0.0.0.0`, which
# would put a personal corpus on the network.
HOST: Final = "127.0.0.1"

# The kernel picks, and the record says which.
ANY_PORT: Final = 0

# How often the main thread looks up from waiting, so a signal's handler
# runs promptly on every platform.
_WAKE_SECONDS: Final = 0.5

_LOG: Final = logging.getLogger("kennis.service")


def port_of(server: uvicorn.Server, timeout: float = 10.0) -> int:
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
        idle.wait(0.02)
    raise RuntimeError("the service did not start listening")


# How long a starting service waits for the owner lock. `is_held` takes the
# lock and lets go to ask whether a service owns the corpus, and the launcher
# asks every 50 ms while this one starts: tried once, a probe's moment was
# read as another service, this one exited, and the launcher reported a
# failed start (#534). A probe lets go within microseconds; another service
# holds the lock for its life, so this still turns away from one.
OWNER_PATIENCE_SECONDS: Final = 2.0


def run_service(corpus_root: Path) -> int:
    """Own the corpus at `corpus_root` until stopped. The exit status.

    Refused at once for a folder that is no corpus: a service with nothing
    to own would hold a lock and a port for thirty minutes, and every
    command that reached it would fail one request later than it should.
    """
    if not holds_a_corpus(corpus_root):
        return NO_CORPUS
    lock = owner_lock(corpus_root)
    try:
        lock.acquire(timeout=OWNER_PATIENCE_SECONDS)
    except Timeout:
        # Another service owns it; the client that started this one will
        # find that one through its record.
        return 0
    try:
        return _serve(corpus_root)
    finally:
        remove_record(corpus_root)
        lock.release()


def _serve(corpus_root: Path) -> int:
    start_logging()
    # Before anything can be asked of it: a publish a killed service left
    # half done is put back, and what such a process leaves behind cleared
    # (14e, #507). The owner lock says no other service is writing.
    with exclusively(corpus_root):
        undone = recover(corpus_root)
    if undone is not None:
        _LOG.warning(
            "the service for %s found a write (%s) left half made by a stopped "
            "service and put the corpus back as it was before it",
            corpus_root,
            undone,
        )
    stopping = threading.Event()
    settings = load_settings()

    def busy() -> bool:
        return bool(app.state.jobs.unfinished())

    idle = IdleTimer(settings.service.idle_minutes * 60, busy, stopping.set)
    token = new_token()
    app = build_service_app(token, corpus_root, on_stop=stopping.set, idle=idle)
    app.state.recovered.put(undone)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=ANY_PORT,
            log_level="warning",
            # The access log would carry a window's token in a query string.
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True, name="kennis-service")
    thread.start()
    try:
        port = port_of(server)
        write_record(
            corpus_root,
            ServiceRecord(
                address=f"http://{HOST}:{port}/",
                token=token,
                pid=os.getpid(),
                started=datetime.now().astimezone(),
                version=__version__,
                corpus=str(corpus_root),
            ),
        )
        _LOG.info("the service for %s listens on port %d", corpus_root, port)
        _stop_on_terminate(stopping, busy)
        idle.start()
        while not stopping.wait(_WAKE_SECONDS):
            if not thread.is_alive():
                _LOG.error("the service's server stopped by itself")
                return 1
        _LOG.info("the service for %s is stopping", corpus_root)
        return 0
    finally:
        idle.stop()
        server.should_exit = True
        thread.join(timeout=10)


def _stop_on_terminate(stopping: threading.Event, busy: Callable[[], bool]) -> None:
    """`SIGTERM` is a stop request: refused while a job runs, as the others
    are. Windows sends none; `kennis service stop` asks over HTTP there."""
    # Only the main thread may set a handler; a test that runs the service
    # on a thread stops it by request instead.
    if threading.current_thread() is not threading.main_thread():
        return
    # The POSIX arm of a platform check, not a return before the handler:
    # mypy checking for Windows calls a statement after such a return
    # unreachable.
    if sys.platform != "win32":

        def terminated(number: int, frame: object) -> None:
            if busy():
                _LOG.warning("asked to stop while a task runs; left running")
                return
            stopping.set()

        signal.signal(signal.SIGTERM, terminated)


__all__ = ["ANY_PORT", "HOST", "OWNER_PATIENCE_SECONDS", "port_of", "run_service"]
