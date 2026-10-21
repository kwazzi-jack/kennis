"""The two versions a pack file carries: the schema it is written in, and
the version a new pack starts at.

Constants alone, so that `kennis pack init`'s options can name a default
without the client importing the schema's models (#535).
"""

from __future__ import annotations

from typing import Final

SCHEMA_VERSION: Final = 1

DEFAULT_VERSION: Final = "0.1.0"

__all__ = ["DEFAULT_VERSION", "SCHEMA_VERSION"]
