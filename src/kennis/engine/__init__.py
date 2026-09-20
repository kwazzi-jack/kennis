"""The engine: everything kennis can do, with no opinion about how it is shown.

An operation here returns a typed result and raises a domain exception. It
never prints, never formats for a particular interface, and never imports one.
Progress and per-item outcomes leave through the event stream in `events`, so
the command line, the MCP server and a future graphical interface are all
subscribers rather than special cases.

A test walks the imports of every module under this package and fails if one
of them reaches for `kennis.cli`, `kennis.mcp`, `click`, `rich`, `rich_click`
or `prompt_toolkit`.
"""

from __future__ import annotations
