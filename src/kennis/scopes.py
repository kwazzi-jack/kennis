"""The scopes a search may cover, by name.

Beside `retrieval.py`, which searches them, and apart from it so that a
client offering them as choices imports none of the search (#535).
"""

from __future__ import annotations

from typing import Final

from kennis.engine.context.groups import CONTEXT_COLLECTION
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.tags import ANNOTATIONS_SCOPE

# The five scopes a search may cover, in the order a report lists
# them. Fixed rather than ranked: ordering groups by their best hit
# would state a comparison across collections that kennis cannot
# make. `context` leads because a bundle is the nearest knowledge;
# `annotations`, the reader's comments, is last because it is not a
# collection of documents but notes on them (#50).
SCOPE_NAMES: Final[tuple[str, ...]] = (
    CONTEXT_COLLECTION,
    *COLLECTION_NAMES,
    ANNOTATIONS_SCOPE,
)

# What the reader types, or picks, to mean all of them.
EVERY_SCOPE: Final = "all"

# The most hits one scope gives a caller that names its own number. Here
# rather than beside the search, so a client that bounds what it was asked
# for loads none of it.
MAX_TOP_K: Final = 20

__all__ = ["EVERY_SCOPE", "MAX_TOP_K", "SCOPE_NAMES"]
