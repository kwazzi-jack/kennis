"""One writer per corpus.

The corpus is a directory of files and a git repository, and two kennis
processes writing to it at once would interleave commits, stage each other's
half-written documents, and swap indexes under one another.

**`timeout=0`, so a second caller is told rather than left waiting.** A
command that blocks gives the user a terminal that has stopped with nothing
said and nothing to press; one that refuses gives them a sentence and their
prompt back. There is no background service to queue behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from filelock import FileLock, Timeout

from kennis.engine.errors import CorpusBusy

# Hidden and suffixed, so `.gitignore` can name it and nothing mistakes it
# for a document: it lives inside the repository the corpus is.
_LOCK_FILE: Final = ".kennis.lock"


def lock_path(root: Path | str) -> Path:
    """Where the lock for the corpus at `root` lives."""
    return Path(root) / _LOCK_FILE


@contextmanager
def corpus_lock(root: Path | str) -> Iterator[None]:
    """Hold the corpus at `root` for the duration of the block.

    Raises `CorpusBusy` immediately if another process holds it. The lock is
    released when the block ends, including when it ends by raising - a
    command that failed must not leave the corpus locked.
    """
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=0)
    try:
        lock.acquire()
    except Timeout as timed_out:
        raise CorpusBusy(
            f"another kennis command is using the corpus at {Path(root)}"
        ) from timed_out
    try:
        yield
    finally:
        lock.release()
