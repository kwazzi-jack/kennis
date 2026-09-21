"""History: the corpus as a git repository.

Git answers what changed; kennis answers what it is. This package is the
first half - a thin wrapper over the binary, and the repository operations
built on it.
"""

from __future__ import annotations

from kennis.engine.history.freshness import Freshness, IndexState, index_freshness
from kennis.engine.history.git import GitResult, git, git_binary
from kennis.engine.history.repository import Repository, initialise_corpus

__all__ = [
    "Freshness",
    "GitResult",
    "IndexState",
    "Repository",
    "git",
    "git_binary",
    "index_freshness",
    "initialise_corpus",
]
