"""What became of a write, as the window shows it.

A module of its own because `pages` and `words` both build one, and
`pages` imports `words`: the class in either would make the two
import each other.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ShownOutcome"]


@dataclass(frozen=True, slots=True)
class ShownOutcome:
    """What became of a write, in the pieces a page arranges.

    `role` is a semantic role name from `render/theme.py`, so the
    template applies a class and decides nothing: whether a repeated
    note is good news or a warning is a judgement, and judgements do
    not belong in markup.
    """

    message: str
    role: str
    where: str | None = None
    resolution: str | None = None
    # Whether the form that produced this should empty itself.
    # A write that happened leaves stale text behind, and pressing
    # the button again writes it twice; a write that was refused
    # leaves text the reader would otherwise have to type again.
    clears: bool = False
    # What else the write did that the reader should know of: documents
    # deleted by hand that it put back.
    notes: tuple[str, ...] = ()
    # The collection to offer an Index now button for, when what was
    # written cannot be found until it is indexed.
    index_after: str | None = None
