"""The MCP server: a second front end over the same engine.

Design section 20. No front end is privileged - the command line is not
the real kennis with a wrapper bolted on - so this package renders and
adapts, and reaches for `engine/` and `render/` for everything else.

Two things are specific to this front end and live here rather than in
`render/`. The `instructions=` block is words for exactly one consumer,
and the tool signatures are this protocol's shape. Everything a user
could also read - a search hit, a diagnostic, what the installation
holds - comes from `render/`, so the two front ends cannot drift.

**stdout is the JSON-RPC wire.** Nothing in this package, or in anything
it imports, may write to it. Design section 14, and
`tests/test_mcp_server.py` holds it to that in a subprocess.
"""

from __future__ import annotations
