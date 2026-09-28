"""Two locks, guarding two different things.

**The corpus lock** covers the documents and the git repository. Two
kennis processes writing there at once would interleave commits and
stage each other's half-written documents.

**An index lock, one per collection**, covers a build, its swap and
its pointer. Design section 16 asks for it at
`index/<collection>/.lock`, and it is separate from the corpus lock
for a reason that is the point of the whole arrangement: a rebuild
takes minutes and a note takes milliseconds, so one lock for both
meant a note written during a rebuild was refused and lost. With two,
the documents stay writable and only the rebuild waits. Concern #167.

Section 16 also says git's own `index.lock` serialises writers to the
documents, so that no second mechanism is needed there. **That is not
true as built**: kennis shells out one git command at a time, so
git's lock protects git's index for the length of one command and
nothing between commands. The corpus lock stays.

**`timeout=0` on both, so a second caller is told rather than left
waiting.** A command that blocks gives the user a terminal that has
stopped with nothing said and nothing to press; one that refuses
gives them a sentence and their prompt back. There is no background
service to queue behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from filelock import FileLock, Timeout

from kennis.engine.errors import CorpusBusy, IndexBusy

# Hidden and suffixed, so `.gitignore` can name it and nothing mistakes it
# for a document: it lives inside the repository the corpus is.
_LOCK_FILE: Final = ".kennis.lock"

# Beside the index it guards, and hidden, so that it is not mistaken
# for part of the index and so that one collection's build does not
# make another collection's wait.
_INDEX_LOCK_FILE: Final = ".lock"


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


def index_lock_path(index_root: Path | str, collection: str) -> Path:
    """Where the lock for one collection's index lives."""
    return Path(index_root) / collection / _INDEX_LOCK_FILE


@contextmanager
def index_lock(index_root: Path | str, collection: str) -> Iterator[None]:
    """Hold one collection's index for the duration of the block.

    Raises `IndexBusy` immediately if another process holds it.

    **Reentrant within a process**, because `filelock` is: a build
    that reached here with the lock already held by this thread would
    proceed rather than deadlock. That is why a test of contention has
    to hold the lock from another thread, and why nothing in kennis
    may rely on this raising against itself.
    """
    path = index_lock_path(index_root, collection)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=0)
    try:
        lock.acquire()
    except Timeout as timed_out:
        raise IndexBusy(
            f"the {collection} index is being rebuilt by another kennis process"
        ) from timed_out
    try:
        yield
    finally:
        lock.release()


__all__ = ["corpus_lock", "index_lock", "index_lock_path", "lock_path"]
