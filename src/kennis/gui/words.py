"""What the graphical interface says.

Beside `mcp/tools/*`, which compose their own sentences for the same
reason: `render/` holds what every front end says about an engine
value, and each front end holds what only it says. "Load images" is
not a fact about a document - it is a control on a page.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.render.words import joined

NOTHING_FOUND = "No passages matched."

IMAGES_BLOCKED = (
    "This document refers to figures held elsewhere. They were not fetched, "
    "because requesting one tells the site which document is being read."
)

LOAD_IMAGES = "Load them"


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return f"There is no scope called '{asked}'. The scopes are {joined(list(scopes))}."


__all__ = ["IMAGES_BLOCKED", "LOAD_IMAGES", "NOTHING_FOUND", "unknown_scope"]
