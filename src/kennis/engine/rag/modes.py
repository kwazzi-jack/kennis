"""Which legs a search runs.

On its own so that a client offering the choice imports nothing of the
search itself (#535).
"""

from __future__ import annotations

from typing import Literal

type Mode = Literal["hybrid", "dense", "bm25"]

__all__ = ["Mode"]
