"""What the graphical interface says.

Beside `mcp/tools/*`, which compose their own sentences for the same
reason: `render/` holds what every front end says about an engine
value, and each front end holds what only it says. "Load images" is
not a fact about a document - it is a control on a page.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.holdings import Holding
from kennis.render.words import count_of, describe_freshness, joined

NOTHING_FOUND = "No passages matched."

IMAGES_BLOCKED = (
    "This document refers to figures held elsewhere. They were not fetched, "
    "because requesting one tells the site which document is being read."
)

LOAD_IMAGES = "Load them"

NEVER_INDEXED = "never indexed"

CORPUS_CHANGED = "The corpus has changed since this page was drawn. Reload to see it."

NOTHING_HELD = "This corpus holds no documents yet."

NO_PACKS = "No packs are installed."


def describe_holding(holding: Holding) -> str:
    """How far one collection's index has fallen behind, for a cell.

    An index that was never built says so in its own words rather than
    borrowing `describe_freshness`, which has no case for it: the
    command line simply prints nothing and moves to the next
    collection, and a table has a cell that must say something.
    """
    if holding.freshness is None:
        return NEVER_INDEXED
    return describe_freshness(holding.freshness, holding.collection)


def unreadable_note(count: int) -> str | None:
    """A listing that omitted documents says how many and why.

    None when there are none, so a page shows nothing rather than "0
    could not be read", which reads as a fault report about a corpus
    that is fine.
    """
    if not count:
        return None
    return (
        f"{count_of(count, 'document')} could not be read and "
        "are not listed. Run `kennis corpus status`."
    )


def describe_count(holding: Holding) -> str:
    """The document count, and the unreadable ones if there are any.

    The second half is never omitted when it applies. A collection
    reported as holding twelve when it holds thirteen, one of them
    broken, has been described falsely - the same rule `list_corpus`
    follows for the same reason.
    """
    counted = count_of(holding.documents, "document")
    if not holding.unreadable:
        return counted
    return f"{counted}, {holding.unreadable} unreadable"


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return f"There is no scope called '{asked}'. The scopes are {joined(list(scopes))}."


__all__ = [
    "CORPUS_CHANGED",
    "IMAGES_BLOCKED",
    "LOAD_IMAGES",
    "NEVER_INDEXED",
    "NOTHING_FOUND",
    "NOTHING_HELD",
    "NO_PACKS",
    "describe_count",
    "describe_holding",
    "unknown_scope",
    "unreadable_note",
]
