"""The scopes a search may cover, by name.

Beside `retrieval.py`, which searches them, and apart from it so that a
client offering them as choices imports none of the search (#535).
"""

from __future__ import annotations

from typing import Final

from kennis.engine.context.groups import CONTEXT_COLLECTION
from kennis.engine.corpus.schema import COLLECTION_NAMES

# The four scopes a search may cover, in the order a report lists
# them. Fixed rather than ranked: ordering groups by their best hit
# would state a comparison across collections that kennis cannot
# make. `context` leads because a bundle is the nearest knowledge.
SCOPE_NAMES: Final[tuple[str, ...]] = (CONTEXT_COLLECTION, *COLLECTION_NAMES)

# What the reader types, or picks, to mean all four.
EVERY_SCOPE: Final = "all"

__all__ = ["EVERY_SCOPE", "SCOPE_NAMES"]
