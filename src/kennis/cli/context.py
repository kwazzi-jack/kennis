"""What every command resolves before it does anything.

**Settings are read once, here, and passed down as values.** Nothing under
`engine/` calls `load_settings`, which is concern #87's rule: an engine that
reads a global is an engine two callers cannot use differently in one
process, and the MCP server serving several workspaces will be exactly that.
This module is the edge the rule names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.corpus.layout import default_corpus_root
from kennis.engine.settings import Settings, load_settings

_ROOT_VARIABLE: Final = "KENNIS_CORPUS_ROOT"


@dataclass(frozen=True, slots=True)
class Context:
    """The resolved answers a command needs before it starts."""

    settings: Settings
    corpus_root: Path


def resolve_context() -> Context:
    """Settings, and where the corpus is.

    The root comes from `KENNIS_CORPUS_ROOT`, then `corpus.root` in the
    settings, then the platform data directory - the same precedence every
    other setting has, with the environment first.
    """
    settings = load_settings()
    return Context(settings=settings, corpus_root=_root_from(settings))


def _root_from(settings: Settings) -> Path:
    override = os.environ.get(_ROOT_VARIABLE)
    if override:
        return Path(override).expanduser()
    if settings.corpus.root:
        return Path(settings.corpus.root).expanduser()
    return default_corpus_root()
