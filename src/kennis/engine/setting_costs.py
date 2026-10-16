"""What changing a setting costs, as data (#410).

Four costs, and a setting may carry more than one. `next_search` and
`next_add` take effect the next time kennis searches or adds; `rebuild`
leaves every index on what it was built with until it is rebuilt, because
an index records its model and chunk size in `binding.json` and a query
embedded by another model is compared against vectors it cannot be
compared against; `leaves_machine` sends document text to a third party
(rules.md 4.5).

Keyed by value as well as by key, because only the hosted backends send
anything away. The words are in `render/settings.py`, so every front end
says the same thing about the same change.
"""

from __future__ import annotations

from typing import Final, Literal

type SettingCost = Literal["next_search", "next_add", "rebuild", "leaves_machine"]

# The host is absent from the binding, so moving an embedding daemon
# changes no stored vector, only where the next query is embedded.
_COSTS: Final[dict[str, tuple[SettingCost, ...]]] = {
    "embedding.backend": ("rebuild",),
    "embedding.model": ("rebuild",),
    "embedding.base_url": ("next_search",),
    "embedding.api_key": ("next_search",),
    "conversion.backend": ("next_add",),
    "conversion.mode": ("next_add",),
    "conversion.api_key": ("next_add",),
    "retrieval.corpus_method": ("next_search",),
    "retrieval.default_top_k": ("next_search",),
    "chunking.size": ("rebuild",),
    # Sends a DOI and this address to Unpaywall, not a document's text, so
    # it is not `leaves_machine`; setting it is the asking (#475).
    "literature.unpaywall_email": ("next_add",),
}

# The values that send document text off this machine, per key.
_HOSTED: Final[dict[str, frozenset[str]]] = {
    "embedding.backend": frozenset({"openai"}),
    "conversion.backend": frozenset({"datalab"}),
}

# Every key with a cost recorded, for a caller that sets keys of both kinds.
COSTED: Final = frozenset(_COSTS)

# Settings with no cost to state, because no front end offers to change
# them where a cost would be read: `corpus.root` moves the corpus itself.
COSTLESS: Final = frozenset({"corpus.root"})


def costs_of(key: str, value: str) -> tuple[SettingCost, ...]:
    """What setting `key` to `value` costs.

    Raises `KeyError` for a key with no cost recorded, including those in
    `COSTLESS`, so a caller cannot read an empty tuple as "free".
    """
    costs = _COSTS[key]
    if value in _HOSTED.get(key, frozenset()):
        return (*costs, "leaves_machine")
    return costs


__all__ = ["COSTED", "COSTLESS", "SettingCost", "costs_of"]
