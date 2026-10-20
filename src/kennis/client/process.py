"""Find the corpus's service, or start one (14b).

**Started detached, from this interpreter.** `sys.executable -m
kennis.service`, never a `kennis` found on `PATH`, so the service is the
same installation as the client - including under `uv tool`. It is started
through a launcher this client waits for (`service/launch.py`), so the
service is never this process's child, and nothing is inherited
(`protocol/spawn.py`).

**One version at a time.** A service of another kennis version is asked to
stop when it is idle and replaced; a busy one is waited for, because
stopping it would end its job wherever it was.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import httpx

from kennis import __version__
from kennis.engine.errors import ServiceBusy, ServiceUnavailable
from kennis.engine.settings import log_dir
from kennis.protocol.record import ServiceRecord, find_service, is_held
from kennis.protocol.spawn import (
    NO_CORPUS,
    STILL_STARTING,
    holds_a_corpus,
    service_command,
    spawned,
)
from kennis.protocol.wire import API_VERSION

# How long a starting service has to answer. Importing the engine and
# binding a port is about a second here; the bound is for a slow disk.
_START_SECONDS: Final = 30.0
# How long a stopping service has to let go of its lock.
_STOP_SECONDS: Final = 10.0
# How often a busy service of another version is asked again.
_BUSY_POLL_SECONDS: Final = 1.0
_POLL_SECONDS: Final = 0.05
_HELLO_SECONDS: Final = 5.0


def hello(record: ServiceRecord) -> dict[str, object] | None:
    """The service's answer to who it is, or None when it does not answer."""
    try:
        answer = httpx.get(
            f"{record.address}api/{API_VERSION}/hello",
            headers={"Authorization": f"Bearer {record.token}"},
            timeout=_HELLO_SECONDS,
        )
    except httpx.HTTPError:
        return None
    if answer.status_code != 200:
        return None
    document: dict[str, object] = answer.json()
    return document


def ensure_service(
    corpus_root: Path, *, on_waiting: Callable[[str], None] | None = None
) -> ServiceRecord:
    """The running service for `corpus_root`, started if there is none.

    `on_waiting` is told, once, when a busy service of another version
    holds the corpus and this waits for it to finish.
    """
    told = False
    while True:
        record = find_service(corpus_root)
        if record is None:
            return _started(corpus_root)
        answered = hello(record)
        if answered is None:
            # Starting, or stopping, or hung: the lock decides which.
            if _wait_for_record(corpus_root, record.pid):
                continue
            raise ServiceUnavailable(
                f"the kennis service (process {record.pid}) holds the corpus "
                "and does not answer; end that process to start another"
            )
        if answered.get("kennis") == __version__:
            return record
        if answered.get("busy"):
            if on_waiting is not None and not told:
                on_waiting(str(answered.get("kennis")))
                told = True
            time.sleep(_BUSY_POLL_SECONDS)
            continue
        stop_service(corpus_root, record)


def stop_service(corpus_root: Path, record: ServiceRecord) -> None:
    """Ask the service to stop and wait for its lock to be let go.

    Raises `ServiceBusy` when a task is running, and `ServiceUnavailable`
    when it does not answer or does not let go.
    """
    try:
        answer = httpx.post(
            f"{record.address}api/{API_VERSION}/stop",
            headers={"Authorization": f"Bearer {record.token}"},
            timeout=_STOP_SECONDS,
        )
    except httpx.HTTPError:
        raise ServiceUnavailable(
            f"the kennis service (process {record.pid}) did not answer"
        ) from None
    if answer.status_code == 409:
        raise ServiceBusy()
    deadline = time.monotonic() + _STOP_SECONDS
    while time.monotonic() < deadline:
        if not is_held(corpus_root):
            return
        time.sleep(_POLL_SECONDS)
    raise ServiceUnavailable(f"the kennis service (process {record.pid}) did not stop")


def _wait_for_record(corpus_root: Path, pid: int) -> bool:
    """Whether the service at `pid` comes to answer, or lets go, in time."""
    deadline = time.monotonic() + _START_SECONDS
    while time.monotonic() < deadline:
        record = find_service(corpus_root)
        if record is None or record.pid != pid:
            return True
        if hello(record) is not None:
            return True
        time.sleep(_POLL_SECONDS)
    return False


def _started(corpus_root: Path) -> ServiceRecord:
    status = start_detached(corpus_root)
    if status not in {0, STILL_STARTING} and not is_held(corpus_root):
        # Exited without a service holding the corpus: it failed, and its
        # stderr went nowhere, so the log is where it said why.
        raise ServiceUnavailable(
            f"the kennis service exited with status {status}; its log is in {log_dir()}"
        )
    deadline = time.monotonic() + _START_SECONDS
    while time.monotonic() < deadline:
        record = find_service(corpus_root)
        if record is not None and hello(record) is not None:
            return record
        time.sleep(_POLL_SECONDS)
    raise ServiceUnavailable(
        f"the kennis service did not answer within {_START_SECONDS:.0f} seconds; "
        f"its log is in {log_dir()}"
    )


def start_detached(corpus_root: Path) -> int:
    """Start the service for `corpus_root` through the launcher, and return
    the launcher's status once it has exited (`service/launch.py`)."""
    if not holds_a_corpus(corpus_root):
        return NO_CORPUS
    launcher = spawned([*service_command(corpus_root), "--launch"], cwd=corpus_root)
    try:
        return launcher.wait(timeout=_START_SECONDS + _STOP_SECONDS)
    except subprocess.TimeoutExpired:
        launcher.kill()
        return launcher.wait()


__all__ = [
    "ServiceBusy",
    "ServiceUnavailable",
    "ensure_service",
    "hello",
    "start_detached",
    "stop_service",
]
