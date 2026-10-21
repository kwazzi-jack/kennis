"""A connection to the corpus's service (14c).

`connect` is the one place a client reaches the service: it makes sure the
service runs and returns an HTTP client bound to its API and token. Tests
replace it, for every test, with one bound to an application in the test's
own process (`tests/in_process.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import httpx

from kennis.client.process import ensure_service
from kennis.protocol.wire import API_VERSION

# A read waits for the service's answer however long a search takes the
# first time, when the model loads; a job's events stream for as long as
# the job runs. Connecting is the part that should be quick.
_TIMEOUT: Final = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)


def connect(corpus_root: Path) -> httpx.Client:
    """An HTTP client for the service that owns the corpus at `corpus_root`."""
    record = ensure_service(corpus_root)
    return httpx.Client(
        base_url=f"{record.address}api/{API_VERSION}/",
        headers={"Authorization": f"Bearer {record.token}"},
        timeout=_TIMEOUT,
    )


__all__ = ["connect"]
