"""The launcher: the short-lived parent a service is started through (14b).

A client that started the service directly would be its parent for as
long as the client lives. Python warns when a running child's handle is
dropped, and on POSIX a child that exits stays a zombie until its parent
reaps it - which an MCP server running for days never would. So a client
starts this launcher instead, and waits for it: the launcher starts the
service, waits until it holds the corpus or has exited, and exits itself.
The client reaps the launcher; the service, its parent gone, belongs to
the system.

Its exit status is the client's report of the start: 0 when a service
holds the corpus (this one, or another that won the race), the service's
own status when it exited first, and `STILL_STARTING` when neither
happened in time, after which the client goes on looking for the record.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

from kennis.protocol.record import is_held, read_record
from kennis.protocol.spawn import (
    NO_CORPUS,
    STILL_STARTING,
    holds_a_corpus,
    service_command,
    spawned,
)

_START_SECONDS: Final = 30.0
_POLL_SECONDS: Final = 0.05


def launch(corpus_root: Path) -> int:
    """Start the service for `corpus_root` and say how the start went."""
    if not holds_a_corpus(corpus_root):
        return NO_CORPUS
    service = spawned(service_command(corpus_root), cwd=corpus_root)
    deadline = time.monotonic() + _START_SECONDS
    while time.monotonic() < deadline:
        if is_held(corpus_root) and read_record(corpus_root) is not None:
            return 0
        status = service.poll()
        if status is not None:
            return 0 if is_held(corpus_root) else (status or 1)
        time.sleep(_POLL_SECONDS)
    return STILL_STARTING


__all__ = ["launch"]
