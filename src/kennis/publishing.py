"""The lock that makes a publish whole to every reader (14e, #507).

One reader-writer lock per corpus in this process, which is the service: a
publish - placing what an operation prepared, and committing it - holds it
exclusively, and a read of the collections holds it shared. A read
therefore sees an operation wholly before or after it, and waits at most
for a publish, because preparing holds nothing (`engine/staging.py`).

**Writer-preferring**, so a publish waiting behind a read is not starved by
the reads that arrive after it. **Reentrant within a thread** for both
kinds, because readers nest - a page's reads call other reads - and an
exclusive holder may read what it is publishing. A thread that holds the
lock shared and asks for it exclusively is refused: two readers doing that
at once would each wait for the other for ever.

The exclusive hold also takes the corpus's file lock, which waits for its
holder rather than refusing (e2): inside the service every write is the
service's own, and the only other holder can be another kennis process,
which a wait outlasts.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Concatenate, Protocol

from kennis.engine.locking import corpus_lock


class UpgradeRefused(RuntimeError):
    """A thread holding the corpus to read asked to publish. A defect in
    kennis rather than something a person did, so not a `KennisError`."""


@dataclass
class _ReadersAndWriter:
    condition: threading.Condition = field(default_factory=threading.Condition)
    readers: dict[int, int] = field(default_factory=dict)
    writer: int | None = None
    depth: int = 0
    waiting_writers: int = 0

    def acquire_shared(self) -> None:
        me = threading.get_ident()
        with self.condition:
            if self.writer == me or me in self.readers:
                self.readers[me] = self.readers.get(me, 0) + 1
                return
            self.condition.wait_for(
                lambda: self.writer is None and self.waiting_writers == 0
            )
            self.readers[me] = 1

    def release_shared(self) -> None:
        me = threading.get_ident()
        with self.condition:
            held = self.readers[me] - 1
            if held:
                self.readers[me] = held
            else:
                del self.readers[me]
                self.condition.notify_all()

    def acquire_exclusive(self) -> None:
        me = threading.get_ident()
        with self.condition:
            if self.writer == me:
                self.depth += 1
                return
            if me in self.readers:
                raise UpgradeRefused(
                    "a thread reading the corpus asked to publish to it"
                )
            self.waiting_writers += 1
            try:
                self.condition.wait_for(
                    lambda: self.writer is None and not self.readers
                )
            finally:
                self.waiting_writers -= 1
            self.writer = me
            self.depth = 1

    def release_exclusive(self) -> None:
        with self.condition:
            self.depth -= 1
            if not self.depth:
                self.writer = None
                self.condition.notify_all()


_LOCKS: dict[Path, _ReadersAndWriter] = {}
_REGISTRY = threading.Lock()


def _lock_for(corpus_root: Path) -> _ReadersAndWriter:
    key = corpus_root.resolve()
    with _REGISTRY:
        return _LOCKS.setdefault(key, _ReadersAndWriter())


@contextmanager
def exclusively(corpus_root: Path) -> Iterator[None]:
    """Hold the corpus to publish: no read of the collections runs, and no
    other kennis process writes, until the block ends."""
    lock = _lock_for(corpus_root)
    lock.acquire_exclusive()
    try:
        if lock.depth == 1:
            with corpus_lock(corpus_root):
                yield
        else:
            yield
    finally:
        lock.release_exclusive()


@contextmanager
def shared(corpus_root: Path) -> Iterator[None]:
    """Hold the corpus to read: no publish runs until the block ends."""
    lock = _lock_for(corpus_root)
    lock.acquire_shared()
    try:
        yield
    finally:
        lock.release_shared()


class _OfACorpus(Protocol):
    @property
    def corpus_root(self) -> Path: ...


def reading[Of: _OfACorpus, **Parameters, Result](
    function: Callable[Concatenate[Of, Parameters], Result],
) -> Callable[Concatenate[Of, Parameters], Result]:
    """A read of the collections, given the context first: it holds the
    context's corpus shared for its length, so it never sees half of a
    publish. For `holdings.py` and `finding.py`, which every front end and
    the service's read calls go through."""

    @functools.wraps(function)
    def held(
        context: Of, /, *arguments: Parameters.args, **options: Parameters.kwargs
    ) -> Result:
        with shared(context.corpus_root):
            return function(context, *arguments, **options)

    return held


__all__ = ["UpgradeRefused", "exclusively", "reading", "shared"]
