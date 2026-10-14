"""The window's layout as the reader left it: three sizes and the strip.

**Each is a cookie the server draws onto `<html>`**, for the reason the
pane's open state is: read after paint, every page would draw at the
default sizes and then jump. A size's name is its cookie and its custom
property at once, so there is one spelling to keep in step.

A size is in pixels, because that is what a pointer measures. It is
drawn only when the cookie is an integer within its bounds: this one
becomes CSS, and anything can be in a cookie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class Size:
    """One size the reader may drag, and its bounds in pixels."""

    name: str
    least: int
    most: int

    def admits(self, value: str) -> bool:
        return value.isdigit() and self.least <= int(value) <= self.most


# The pane's least keeps a collection's name and count on one line; the
# strip's least is one line of the strip, so a dragged strip is never
# mistaken for a collapsed one.
SIZES: Final[dict[str, Size]] = {
    size.name: size
    for size in (
        Size("pane-width", 160, 480),
        Size("inspector-width", 200, 560),
        Size("strip-height", 40, 800),
    )
}

_STRIP_COOKIE: Final = "strip"
_CLOSED: Final = "closed"
_OPEN: Final = "open"


def sizes_of(request: Request) -> str:
    """The sizes the reader set, as declarations for `<html>`'s style;
    empty when none is set, so no `style` is drawn at all."""
    return "; ".join(
        f"--{name}: {request.cookies[name]}px"
        for name, size in SIZES.items()
        if size.admits(request.cookies.get(name, ""))
    )


def strip_state(request: Request) -> str:
    """`closed` only for exactly that value, as the pane's rule is."""
    return _CLOSED if request.cookies.get(_STRIP_COOKIE) == _CLOSED else _OPEN


__all__ = ["SIZES", "Size", "sizes_of", "strip_state"]
