"""History: the corpus as a git repository.

Git answers what changed; kennis answers what it is. This package is the
first half - a thin wrapper over the binary, and the repository operations
built on it.
"""

from __future__ import annotations

from kennis.engine.history.freshness import Freshness, IndexState, index_freshness
from kennis.engine.history.git import GitResult, git, git_binary
from kennis.engine.history.history import (
    HistoryEntry,
    RestoredDocument,
    read_history,
    restore_document,
)
from kennis.engine.history.outofband import (
    ChangeKind,
    OutOfBandChange,
    detect_changes,
    restore_deletions,
)
from kennis.engine.history.repository import Repository, initialise_corpus

__all__ = [
    "ChangeKind",
    "Freshness",
    "GitResult",
    "HistoryEntry",
    "IndexState",
    "OutOfBandChange",
    "Repository",
    "RestoredDocument",
    "detect_changes",
    "git",
    "git_binary",
    "index_freshness",
    "initialise_corpus",
    "read_history",
    "restore_deletions",
    "restore_document",
]
