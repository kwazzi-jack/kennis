"""Writes that an interrupt cannot leave half-done.

Two shapes, because kennis's writers come in two kinds and the wrong one does
real damage:

`replace_file` is for a file that replaces an existing one - a corpus
document, a settings file, a converged bundle file. The new bytes land in a
sibling temporary file and are renamed over the target, so a reader sees
either the old content or the new one and never a truncation. Each call stands
alone, which is what keeps a partially-finished run *resumable*: fifteen
papers fetched before a Ctrl-C are fifteen whole papers, and re-running the
command carries on from there.

`replacing_directory` is for an artefact that is only meaningful complete - a
built index. The whole directory is staged beside the target and swapped in at
the end, so the previous one keeps serving for the entire build and an
interrupt costs the work but never the index that was already there. Applying
*this* shape to a corpus fetch would be a regression rather than a fix: it
would throw away every document written before the interrupt.

**What kennis obtained is written read-only** (14g, #514) - a pack's
files in the store, the notes a pack owns, fetched documentation - so an
editor says so before a person changes text kennis will put back. Every
replace and delete here therefore clears the mode first: Windows refuses
to replace or delete a read-only file, where POSIX asks only the
directory.

Both live at the engine root because `corpus`, `rag` and `history` all write,
and a helper in any one of them that the others reached back for would close
an import loop.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

# Staging names are dot-prefixed and carry the target's own name, so a sweep
# can recognise them without a registry and no real corpus or index entry can
# ever collide with one. The walk skips dot-prefixed paths already.
_STAGING_PREFIX = "."
_STAGING_INFIX = ".staging-"
_RETIRED_INFIX = ".retiring-"


def replace_file(
    path: Path, data: str | bytes, *, encoding: str = "utf-8", read_only: bool = False
) -> None:
    """Write `data` to `path` atomically, creating parent directories.

    The target is left untouched if anything goes wrong, including a Ctrl-C
    partway through the write - hence `BaseException` rather than `Exception`.

    **`newline="\n"`, so what kennis writes does not depend on where it is
    running.** Without it Python translates `\n` to `os.linesep`, and every
    corpus document written on Windows landed as CRLF. That is not a
    cosmetic difference: `pack/content.py::content_digest` hashes
    `path.read_bytes()`, so the same logical document digested differently
    on the two platforms and a pack built on Linux failed validation on
    Windows - reported as the file having been tampered with. Reading needs
    no equivalent, because universal newlines already normalise CRLF to LF
    on the way in. Concern #384.

    `read_only` leaves the new file without write permission, which is how
    kennis marks what it obtained (#514).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        if isinstance(data, bytes):
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
        else:
            with os.fdopen(handle, "w", encoding=encoding, newline="\n") as stream:
                stream.write(data)
        if read_only:
            make_read_only(Path(temporary))
        _make_writable(path)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def make_read_only(path: Path) -> None:
    """Take every write permission off `path`; on Windows, set its
    read-only attribute, which is what `chmod` reaches there."""
    path.chmod(stat.S_IMODE(path.stat().st_mode) & ~_WRITE_BITS)


def remove_file(path: Path, *, missing_ok: bool = False) -> None:
    """Delete a file, read-only or not."""
    if missing_ok and not path.exists():
        return
    _make_writable(path)
    path.unlink(missing_ok=missing_ok)


def remove_tree(path: Path, *, ignore_errors: bool = False) -> None:
    """Delete a directory and everything in it, read-only files included."""

    def writable_then_again(
        function: Callable[..., object], name: str, error: BaseException
    ) -> None:
        if not isinstance(error, PermissionError):
            if ignore_errors:
                return
            raise error
        try:
            _make_writable(Path(name))
            function(name)
        except OSError:
            if not ignore_errors:
                raise

    if ignore_errors and not path.exists():
        return
    shutil.rmtree(path, onexc=writable_then_again)


_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def _make_writable(path: Path) -> None:
    """Give the owner write permission back, where it was taken away."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return
    if not mode & stat.S_IWUSR:
        path.chmod(mode | stat.S_IWUSR)


@contextmanager
def replacing_directory(path: Path) -> Iterator[Path]:
    """Yield a staging directory whose contents replace `path` on clean exit.

    The caller writes everything into the yielded path. Only when the block
    finishes without raising is the staging directory swapped in - previous
    contents renamed aside, staging renamed into place, the old one deleted.
    Two renames rather than one, because `os.replace` will not overwrite a
    non-empty directory; the window between them is microseconds against the
    minutes an index build takes, which is the whole point.

    An interrupt inside the block deletes the staging directory and leaves
    `path` exactly as it was.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _sweep_staging(path)
    staging = Path(
        tempfile.mkdtemp(
            dir=path.parent, prefix=f"{_STAGING_PREFIX}{path.name}{_STAGING_INFIX}"
        )
    )
    try:
        yield staging
    except BaseException:
        remove_tree(staging, ignore_errors=True)
        raise

    retired: Path | None = None
    if path.exists():
        retired = Path(
            tempfile.mkdtemp(
                dir=path.parent, prefix=f"{_STAGING_PREFIX}{path.name}{_RETIRED_INFIX}"
            )
        )
        # mkdtemp made it, so it exists, and `os.replace` onto a directory
        # requires that directory to be empty - which it is, until now.
        retired.rmdir()
        os.replace(path, retired)
    try:
        os.replace(staging, path)
    except BaseException:
        if retired is not None:
            os.replace(retired, path)
        remove_tree(staging, ignore_errors=True)
        raise
    if retired is not None:
        remove_tree(retired, ignore_errors=True)


def _sweep_staging(path: Path) -> None:
    """Remove staging directories a previous run could not clean up itself.

    `replacing_directory` deletes its own on any exception, so this only ever
    finds one left by a kill that ran no handlers at all (SIGKILL, power
    loss). Left alone they would be a full copy of an index sitting on disk
    forever, so the next build of the same target clears them.
    """
    for candidate in path.parent.glob(f"{_STAGING_PREFIX}{path.name}.*"):
        name = candidate.name
        if _STAGING_INFIX in name or _RETIRED_INFIX in name:
            remove_tree(candidate, ignore_errors=True)
