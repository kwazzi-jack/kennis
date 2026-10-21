"""What a person does to a file kennis made read-only.

kennis writes what it obtained read-only (14g, g5), and Windows refuses to
delete or replace such a file until it is made writable - as the suite's
`refusing_as_windows_does` does everywhere. A test standing in for a person
takes the same step a person's tools take.
"""

from __future__ import annotations

import stat
from pathlib import Path


def made_writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWRITE)


def deleted_by_hand(path: Path) -> None:
    """What a file manager's delete does to a read-only file once confirmed."""
    made_writable(path)
    path.unlink()


def edited_by_hand(path: Path, old: str, new: str) -> None:
    """What an editor's "save anyway" does: make the file writable, then
    write."""
    made_writable(path)
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), "utf-8")


__all__ = ["deleted_by_hand", "edited_by_hand", "made_writable"]
