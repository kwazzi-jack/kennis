"""The tools this server exposes.

One module per group, each a thin adapter: resolve where the corpus is,
call the engine, render the answer. Nothing here decides anything the
command line would decide differently.
"""

from __future__ import annotations
