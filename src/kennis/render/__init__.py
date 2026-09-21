"""Turning engine values into words, for every front end.

Three layers, and this is the middle one:

| layer | holds |
|---|---|
| `engine/` | facts - typed values, typed events, domain errors |
| `render/` | words - sentences built from those values |
| `cli/` | layout - colour, alignment, progress bars, terminal width |

**This is deliberately not under `cli/`.** The MCP server needs the same
wording and must not import a command-line package to get it; putting the
words there would make the second front end downstream of the first, which is
exactly the coupling this separation exists to prevent. The dependency runs
`cli -> render -> engine` and never back, and an architecture test enforces
that this package imports no interface library.
"""

from __future__ import annotations

from kennis.render.theme import Role
from kennis.render.words import (
    count_of,
    describe_change,
    describe_freshness,
    remedies_for,
)

__all__ = [
    "Role",
    "count_of",
    "describe_change",
    "describe_freshness",
    "remedies_for",
]
