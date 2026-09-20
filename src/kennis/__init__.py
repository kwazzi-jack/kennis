"""kennis: a knowledge and memory system.

The package itself holds nothing but its version. Everything a caller wants is
under `kennis.engine`; `kennis.cli` is one front end over it and is not
privileged.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # One version, read from the installed distribution rather than written in
    # a second place. Two copies of a version disagree eventually, and the
    # disagreement is always found by a user rather than by a test.
    __version__ = version("kennis")
except PackageNotFoundError:  # pragma: no cover - only when running from a
    # source tree that was never installed, which `uv run` does not do.
    __version__ = "0.0.0"

__all__ = ["__version__"]
