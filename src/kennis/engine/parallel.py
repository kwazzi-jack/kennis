"""Fetching several things at once, without anything else becoming parallel.

Brian, 2026-10-27: requests in parallel wherever a host allows it. Only the
fetch is parallel. What a caller does with a result - converting, writing,
telling two citekeys apart, emitting an event - stays on its own thread, in
the order the items were given, because the corpus is written one document
at a time and a citekey's suffix depends on which paper came first.

How fast one host is asked is not decided here: `courtesy` gates each
origin by its robots.txt, and a caller passes kennis's own pacing as
`spacing` and a host that asks for one request at a time as `workers=1`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Final

# How many requests kennis has in flight at once, to one host or to several.
# Four is a browser's habit halved: enough to hide a slow registry's
# latency, few enough that no host sees kennis as more than a person.
PARALLEL_REQUESTS: Final = 4


def fetched_in_parallel[Item, Result](
    items: Sequence[Item],
    fetch: Callable[[Item], Result],
    *,
    workers: int = PARALLEL_REQUESTS,
    spacing: float | Spacing = 0.0,
    on_fetched: Callable[[Item, Result], None] | None = None,
) -> list[Result]:
    """`fetch` of each item, run on up to `workers` threads, returned in the
    order of `items`.

    Two fetches start at least `spacing` seconds apart; with one worker,
    `spacing` is waited after each fetch ends, which is what a host's
    `Crawl-delay` asks and what the loops this replaced slept. A `Spacing`
    passed in carries the turns across calls, for a caller fetching in
    batches. `on_fetched` is
    called on this thread as each fetch completes, in the order they
    complete, so a caller emits progress from here and never from a worker.
    An exception a fetch raises is raised here, once the fetches not yet
    started are cancelled; those in flight are not waited for.
    """
    if not items:
        return []
    starts = (
        spacing
        if isinstance(spacing, Spacing)
        else Spacing(spacing, one_at_a_time=workers <= 1)
    )

    def started(item: Item) -> Result:
        starts.wait_turn()
        return fetch(item)

    executor = ThreadPoolExecutor(
        max_workers=max(1, min(workers, len(items))),
        thread_name_prefix="kennis-fetch",
    )
    try:
        futures: dict[Future[Result], int] = {
            executor.submit(started, item): position
            for position, item in enumerate(items)
        }
        pending = set(futures)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                if on_fetched is not None:
                    on_fetched(items[futures[future]], result)
        ordered = sorted(futures.items(), key=lambda pair: pair[1])
        return [future.result() for future, _ in ordered]
    finally:
        # Also on Ctrl-C: what has not started never starts, and a request
        # in flight ends by its own timeout.
        executor.shutdown(wait=False, cancel_futures=True)


class Spacing:
    """The earliest moment the next fetch may start, shared by the workers.

    `one_at_a_time` waits the whole `seconds` before every fetch but the
    first, counted from the end of the fetch before, which is right only
    when one worker fetches; otherwise `seconds` spaces the starts.
    """

    def __init__(self, seconds: float, *, one_at_a_time: bool) -> None:
        self._spacing = seconds
        self._one_at_a_time = one_at_a_time
        self._first = True
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def wait_turn(self) -> None:
        if self._spacing <= 0:
            return
        if self._one_at_a_time:
            # One worker, so nothing else reads `_first`: the whole spacing,
            # counted from the end of the fetch before.
            if not self._first:
                time.sleep(self._spacing)
            self._first = False
            return
        with self._lock:
            now = time.monotonic()
            turn = max(now, self._next)
            self._next = turn + self._spacing
        # Slept outside the lock, so the next worker can take its own turn.
        if turn > now:
            time.sleep(turn - now)


__all__ = ["PARALLEL_REQUESTS", "Spacing", "fetched_in_parallel"]
