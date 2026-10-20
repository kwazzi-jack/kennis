"""The corpus held by another writer for a moment (14c).

A write through the service waits for the corpus lock rather than being
refused (14b), so a test of that holds it on another thread, as another
writer would, and lets go after `MOMENT`. Bounded, so a regression in
which the wait never ends fails the command's own assertion rather than
hanging the suite: the holder always lets go.

**The test asserts an order, so it compares two instants.** The command
must finish after the holder lets go. Measuring the time around the block
cannot say that, because leaving the block joins the holder and so always
lasts `MOMENT`, whether or not the command waited.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.locking import corpus_lock

MOMENT: Final = 0.4
_PATIENCE: Final = 30.0


@dataclass(slots=True)
class Hold:
    """When the holder let go, on `time.monotonic`'s clock; infinite until
    then, so a comparison made too early fails."""

    released: float = math.inf


@contextmanager
def held_for_a_moment(corpus: Path) -> Iterator[Hold]:
    """The corpus lock held elsewhere from entry until `MOMENT` later."""
    holding = threading.Event()
    hold = Hold()

    def hold_it() -> None:
        with corpus_lock(corpus):
            holding.set()
            threading.Event().wait(MOMENT)
        hold.released = time.monotonic()

    holder = threading.Thread(target=hold_it, daemon=True)
    holder.start()
    assert holding.wait(_PATIENCE), "the lock was never taken"
    try:
        yield hold
    finally:
        holder.join(_PATIENCE)


__all__ = ["MOMENT", "Hold", "held_for_a_moment"]
