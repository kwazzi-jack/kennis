"""The graphical front end.

A third front end over the same engine, and a **peer** of `cli/` and
`mcp/`: it imports neither, and neither imports it. Design section 20 -
no front end is privileged, so nothing here may become the place a
capability lives.

Served as a local web interface rather than built with native widgets.
The reasoning is in `design/plan.md` under milestone 9 and turns on one
fact about the content: kennis holds converted papers, which are
equations, tables and figures, and a browser renders those natively
where a widget toolkit needs a browser embedded inside it to match.
"""

from __future__ import annotations
