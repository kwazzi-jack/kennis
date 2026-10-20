"""Where a corpus's service is, as a file its clients read (14b).

`gui/instance.py` (#484) generalised from one window to one service per
corpus. Under the state directory each corpus has a lock and a record,
named by a key taken from the corpus's root: the service holds the lock for
its whole life and writes the record once it knows its port.

**The lock is the fact; the record is what it says.** The kernel releases
a lock when its process dies, however it dies, so a record whose lock
nobody holds is a crash's leftover and is removed rather than believed. A
held lock file cannot be deleted on Windows, which is why the record, and
not the lock file, is what a client removes.

**The record carries the token**, readable by this account alone: `0600`
where the platform has file modes, the profile directory's permissions on
Windows (#389). A client cannot reach the service without it.

**The key is the corpus's resolved root**, and on macOS and Windows that
root casefolded, because their file systems ignore case by default and two
spellings of one folder must find one service. A mapped drive and its
network path are not unified.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from filelock import FileLock, Timeout

from kennis.engine.settings import state_dir

_KEY_DIGITS: Final = 16


@dataclass(frozen=True, slots=True)
class ServiceRecord:
    """A running service, as its record says.

    `address` is the base every request is made against, ending in `/`.
    """

    address: str
    token: str
    pid: int
    started: datetime
    version: str
    corpus: str


def corpus_key(root: Path) -> str:
    """The name a corpus's lock and record are kept under."""
    spelled = str(Path(root).expanduser().resolve())
    if sys.platform in {"darwin", "win32"}:
        spelled = spelled.casefold()
    return hashlib.sha256(spelled.encode("utf-8")).hexdigest()[:_KEY_DIGITS]


def lock_path(root: Path) -> Path:
    return state_dir() / f"service-{corpus_key(root)}.lock"


def record_path(root: Path) -> Path:
    return state_dir() / f"service-{corpus_key(root)}.json"


def owner_lock(root: Path) -> FileLock:
    """The lock a service holds for its whole life. Not yet acquired."""
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path), timeout=0)


def write_record(root: Path, record: ServiceRecord) -> None:
    """Write the record whole, readable by this account alone."""
    path = record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "address": record.address,
        "token": record.token,
        "pid": record.pid,
        "started": record.started.isoformat(),
        "version": record.version,
        "corpus": record.corpus,
    }
    # `mkstemp` makes the file `0600` before anything is in it, so the token
    # is never readable by another account, not even for a moment.
    descriptor, partial = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(document, indent=1) + "\n")
        os.chmod(partial, 0o600)
        os.replace(partial, path)
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise


def read_record(root: Path) -> ServiceRecord | None:
    """The record as written, or None when there is none or it is unreadable."""
    try:
        document = json.loads(record_path(root).read_text(encoding="utf-8"))
        return ServiceRecord(
            address=str(document["address"]),
            token=str(document["token"]),
            pid=int(document["pid"]),
            started=datetime.fromisoformat(str(document["started"])),
            version=str(document["version"]),
            corpus=str(document["corpus"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_record(root: Path) -> None:
    record_path(root).unlink(missing_ok=True)


def is_held(root: Path) -> bool:
    """Whether a live process holds the corpus's service lock."""
    if not lock_path(root).exists():
        return False
    probe = FileLock(str(lock_path(root)), timeout=0)
    try:
        probe.acquire()
    except Timeout:
        return True
    probe.release()
    return False


def find_service(root: Path) -> ServiceRecord | None:
    """The service that owns the corpus at `root`, or None.

    None as well while one is starting and has not yet recorded its
    address. A record nobody's lock stands behind is removed.
    """
    if is_held(root):
        return read_record(root)
    remove_record(root)
    return None


__all__ = [
    "ServiceRecord",
    "corpus_key",
    "find_service",
    "is_held",
    "lock_path",
    "owner_lock",
    "read_record",
    "record_path",
    "remove_record",
    "write_record",
]
