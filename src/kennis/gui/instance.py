"""One window process at a time (Brian, 2026-10-17).

A running `kennis gui` holds `gui.lock` in the state directory for its
whole life and records, in `gui.json` beside it, where it is: the address
with its token, the process, when it started and kennis's version. A second
`kennis gui` reads the record and opens that window, or asks it to stop
and takes its place.

**The lock is the fact; the record is what it says.** The kernel releases
a lock when its process dies, however it dies, so a record with no holder
is a crash's leftover and is removed rather than believed.

**The record carries the token**, which `app.py` once said was never
stored. A second launch cannot open or stop the first without it. The
token keeps out other accounts and pages served from other ports
(#309), and neither can read a file only this account may; a process
running as the person can read the corpus itself. It also lets a browser
that has lost its session cookie back in. Concern #484.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import httpx
from filelock import FileLock, Timeout

from kennis import __version__
from kennis.engine.atomic import replace_file
from kennis.engine.errors import KennisError
from kennis.engine.settings import state_dir

_LOCK_NAME: Final = "gui.lock"
_RECORD_NAME: Final = "gui.json"
# How long a stopped window has to let go of its lock. Quit answers first
# and stops after (`routes/shell.py`), and uvicorn waits for requests in
# flight, so this is seconds rather than milliseconds.
_STOP_SECONDS: Final = 10.0


@dataclass(frozen=True, slots=True)
class OpenWindow:
    """A running window, as its record says."""

    address: str
    pid: int
    started: datetime
    version: str


class AlreadyOpen(KennisError):
    """Another kennis window holds the lock."""

    default_message = "another kennis window is already open"
    default_resolution = "kennis gui --replace"

    def __init__(self, window: OpenWindow | None) -> None:
        super().__init__()
        self.window = window


class WindowBusy(KennisError):
    """The open window is running a job, and stopping it would end the job
    wherever it is - inside the corpus lock, or before a commit."""

    default_message = "the open kennis window is running a job and was left open"
    default_resolution = "kennis gui --replace"


class WindowUnreachable(KennisError):
    """The lock is held and the address does not answer."""

    default_resolution = None

    def __init__(self, window: OpenWindow) -> None:
        super().__init__(
            f"the open kennis window (process {window.pid}) did not answer; "
            "end that process to start another"
        )


def lock_path() -> Path:
    return state_dir() / _LOCK_NAME


def record_path() -> Path:
    return state_dir() / _RECORD_NAME


@contextmanager
def this_window() -> Iterator[Callable[[str], None]]:
    """Hold the one window's lock, and hand back what records the address.

    Taken before the server binds, so of two launches at once the second
    is refused rather than serving; the address is known only once the
    kernel has chosen a port, so it is recorded then.
    """
    lock = FileLock(lock_path(), timeout=0)
    lock_path().parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.acquire()
    except Timeout:
        raise AlreadyOpen(_read_record()) from None
    try:
        yield _record
    finally:
        record_path().unlink(missing_ok=True)
        lock.release()


def open_window() -> OpenWindow | None:
    """The window that holds the lock, or None.

    None as well while one is starting and has not yet recorded its
    address: there is nothing to open, and serving will be refused.
    """
    if not lock_path().exists():
        return None
    probe = FileLock(lock_path(), timeout=0)
    try:
        probe.acquire()
    except Timeout:
        return _read_record()
    probe.release()
    # Nobody holds it, so a record is a crashed window's.
    record_path().unlink(missing_ok=True)
    return None


def ask_to_quit(window: OpenWindow) -> None:
    """Stop `window` through its own Quit, and wait for it to let go.

    Its own route, so it refuses while a job runs for the reason it always
    has. Raises `WindowBusy` then, and `WindowUnreachable` when nothing
    answers or the lock is not released.
    """
    base, _, query = window.address.partition("?")
    try:
        answer = httpx.post(f"{base}quit?{query}", timeout=_STOP_SECONDS)
    except httpx.HTTPError:
        raise WindowUnreachable(window) from None
    if answer.status_code == 409:
        raise WindowBusy()
    if answer.status_code != 200:
        raise WindowUnreachable(window)
    deadline = time.monotonic() + _STOP_SECONDS
    while time.monotonic() < deadline:
        probe = FileLock(lock_path(), timeout=0)
        try:
            probe.acquire()
        except Timeout:
            time.sleep(0.1)
            continue
        probe.release()
        return
    raise WindowUnreachable(window)


def _record(address: str) -> None:
    document = {
        "address": address,
        "pid": os.getpid(),
        "started": datetime.now().astimezone().isoformat(),
        "version": __version__,
    }
    replace_file(record_path(), json.dumps(document, indent=1) + "\n")
    # `mkstemp` already made it 0600; stated rather than inherited, as
    # `credentials.toml` is (#389 for what that means on Windows).
    record_path().chmod(0o600)


def _read_record() -> OpenWindow | None:
    try:
        document = json.loads(record_path().read_text(encoding="utf-8"))
        return OpenWindow(
            address=str(document["address"]),
            pid=int(document["pid"]),
            started=datetime.fromisoformat(str(document["started"])),
            version=str(document["version"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


__all__ = [
    "AlreadyOpen",
    "OpenWindow",
    "WindowBusy",
    "WindowUnreachable",
    "ask_to_quit",
    "lock_path",
    "open_window",
    "record_path",
    "this_window",
]
