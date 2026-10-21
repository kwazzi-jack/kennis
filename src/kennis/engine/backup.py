"""An encrypted `.7z` of the corpus, in a folder the person chooses.

kennis talks to no service and configures no remote (#413, #420). The
folder is often one a cloud client synchronises; kennis neither knows nor
asks which. The archive is AES-256 with the names encrypted too, and holds
the corpus folder with its `.git` but not `index/`. The index is derived and
only its pointer and binding are in history, so a restored corpus is
indexed again before it is searched (#443).

**The last good backup is never destroyed.** A backup is written beside it
under a temporary name, opened again with the same password and tested,
and only then renamed over it. Any failure removes the temporary file.

**A wrong password is not one exception.** With the header encrypted, a
wrong key decrypts it into arbitrary bytes, and `py7zr` then fails however
those bytes lead it to: over 300 wrong passwords it raised `TypeError` 298
times and `Bad7zFile` twice. The calls that open an archive therefore map
*any* exception to `BackupUnreadable`, with the original chained for the
log. The catch is around those calls alone, so a defect in kennis is not
hidden by it.
"""

from __future__ import annotations

import os
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

import py7zr

from kennis.engine.corpus.conversions import conversions_root
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import BackupRefused, BackupUnreadable
from kennis.engine.events import EventSink, OperationFinished, Progress
from kennis.engine.history.repository import Repository
from kennis.engine.locking import lock_path
from kennis.engine.staging import journal_path, staging_root

BACKUP_NAME: Final = "kennis-corpus.7z"
_TOP: Final = "corpus"
_OPERATION: Final = "backup"
SET_FOLDER_COMMAND: Final = "kennis config set backup.folder <folder>"

# One archive member: the file on disk and the name it is stored under.
type Member = tuple[Path, str]


@dataclass(frozen=True, slots=True)
class BackupReport:
    path: Path
    size: int
    members: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class BackupCheck:
    """What is known about a backup folder, as facts for a front end.

    `verified` is None when no password was given or there is no archive;
    otherwise it says whether every member opened and matched its checksum.
    """

    folder: Path
    folder_exists: bool
    writable: bool
    archive: Path | None
    size: int | None
    modified: datetime | None
    verified: bool | None


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """What a restore unpacked. The index is never among it: a restored
    corpus is indexed before it is searched."""

    target: Path
    members: int


def members_of(corpus_root: Path) -> list[Member]:
    """Every directory and regular file the backup holds, in a stable order.

    Directories are members too, so a restored `.git` has the empty
    directories git expects. Not `index/`, which is rebuilt, nor the lock
    file or what `.git` holds only while kennis works, which are facts
    about a running process rather than about the corpus. **A
    symbolic link is neither followed nor stored**: kennis never writes one,
    and following one could put a file from outside the corpus into a
    backup that is about to leave the machine.
    """
    excluded = {
        index_root(corpus_root),
        lock_path(corpus_root),
        # Kept in `.git` only while kennis works (14e, #525): a mirror being
        # prepared in, a publish's journal, and conversions kept for a
        # retry - text of documents a failed add may never have added.
        staging_root(corpus_root),
        journal_path(corpus_root),
        conversions_root(corpus_root),
    }
    members: list[Member] = []
    for directory, folders, files in os.walk(corpus_root, followlinks=False):
        here = Path(directory)
        folders[:] = sorted(
            name
            for name in folders
            if here / name not in excluded and not (here / name).is_symlink()
        )
        for name in folders:
            members.append((here / name, _stored_name(corpus_root, here / name)))
        for name in sorted(files):
            path = here / name
            if path in excluded or path.is_symlink() or not path.is_file():
                continue
            members.append((path, _stored_name(corpus_root, path)))
    return members


def write_backup(
    corpus_root: Path,
    folder: Path,
    password: str,
    *,
    events: EventSink | None = None,
) -> BackupReport:
    """Write the corpus to `folder/BACKUP_NAME`, replacing it only once tested."""
    started = time.monotonic()
    if not password:
        raise BackupRefused("a backup needs a password, and none was given")
    _refuse_unusable(folder)

    members = members_of(corpus_root)
    final = folder / BACKUP_NAME
    partial = folder / f".{BACKUP_NAME}.partial-{secrets.token_hex(4)}"
    try:
        with py7zr.SevenZipFile(
            partial, "w", password=password, header_encryption=True
        ) as archive:
            for completed, (path, name) in enumerate(members, start=1):
                archive.write(path, name)
                if events is not None:
                    events.emit(
                        Progress(
                            operation=_OPERATION,
                            completed=completed,
                            total=len(members),
                        )
                    )
        _require_intact(partial, password, {name for _, name in members})
        os.replace(partial, final)
    finally:
        partial.unlink(missing_ok=True)

    elapsed = time.monotonic() - started
    if events is not None:
        events.emit(OperationFinished(operation=_OPERATION, elapsed_seconds=elapsed))
    return BackupReport(
        path=final,
        size=final.stat().st_size,
        members=len(members),
        elapsed_seconds=elapsed,
    )


def check_backup(folder: Path, password: str | None = None) -> BackupCheck:
    """The folder's state and the archive's, testing it if given a password."""
    exists = folder.is_dir()
    archive = folder / BACKUP_NAME
    present = exists and archive.is_file()
    status = archive.stat() if present else None
    verified: bool | None = None
    if present and password:
        try:
            _require_intact(archive, password, None)
            verified = True
        except BackupUnreadable:
            verified = False
    return BackupCheck(
        folder=folder,
        folder_exists=exists,
        writable=exists and os.access(folder, os.W_OK),
        archive=archive if present else None,
        size=status.st_size if status else None,
        modified=datetime.fromtimestamp(status.st_mtime, tz=UTC) if status else None,
        verified=verified,
    )


def restore_backup(archive: Path, target: Path, password: str) -> RestoreReport:
    """Unpack `archive` as a corpus at `target`, which must not hold anything.

    Every name is checked before anything is written, because an archive is
    data from outside: each must lie under `corpus/`, with no `..`.
    Unpacked into a sibling directory and renamed into place, so a failure
    part-way leaves no half-restored corpus behind.
    """
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise BackupRefused(
            f"{target} is not empty, and a restore never writes over a corpus"
        )
    names = _names_in(archive, password)
    outside = [name for name in names if not _inside_the_corpus(name)]
    if outside:
        raise BackupRefused(
            f"{archive} names {outside[0]}, which is outside the corpus; "
            "nothing was restored"
        )

    staging = target.parent / f".{target.name}.restoring-{secrets.token_hex(4)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _extract(archive, password, staging)
        if target.exists():
            target.rmdir()
        os.replace(staging / _TOP, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # The index's pointer and binding are tracked and were not in the
    # archive, so they are checked out to leave the working tree agreeing
    # with HEAD - a missing tracked file is what the next write would take
    # for a deletion by hand. What they point at is built by `corpus index`.
    Repository(target).restore(index_root(target).name)
    return RestoreReport(target=target, members=len(names))


def _stored_name(corpus_root: Path, path: Path) -> str:
    return f"{_TOP}/{path.relative_to(corpus_root).as_posix()}"


def _inside_the_corpus(name: str) -> bool:
    """Whether `name` unpacks inside `corpus/`.

    No separate test for an anchor: a name with one, in either path
    flavour, cannot begin with `corpus`, so the first part decides it.
    A `..` is the case the first part does not decide.
    """
    posix = PurePosixPath(name)
    if ".." in posix.parts or ".." in PureWindowsPath(name).parts:
        return False
    return len(posix.parts) >= 2 and posix.parts[0] == _TOP


def _refuse_unusable(folder: Path) -> None:
    if not folder.is_dir():
        raise BackupRefused(
            f"the backup folder {folder} is not there", resolution=SET_FOLDER_COMMAND
        )
    if not os.access(folder, os.W_OK):
        raise BackupRefused(
            f"the backup folder {folder} cannot be written to",
            resolution=SET_FOLDER_COMMAND,
        )


def _names_in(archive: Path, password: str) -> list[str]:
    try:
        with py7zr.SevenZipFile(archive, "r", password=password) as opened:
            return list(opened.getnames())
    except Exception as error:
        raise BackupUnreadable() from error


def _extract(archive: Path, password: str, into: Path) -> None:
    """Unpack every member, after `restore_backup` has checked the names.

    A checksum that fails here raises from inside the library like a wrong
    password does, so it is caught the same way.
    """
    try:
        with py7zr.SevenZipFile(archive, "r", password=password) as opened:
            opened.extractall(path=into)
    except Exception as error:
        raise BackupUnreadable() from error


def _require_intact(archive: Path, password: str, expected: set[str] | None) -> None:
    """Every member decrypts and matches its checksum, and the names agree."""
    try:
        with py7zr.SevenZipFile(archive, "r", password=password) as opened:
            names = set(opened.getnames())
            failed = opened.testzip()
    except Exception as error:
        raise BackupUnreadable() from error
    if failed is not None:
        raise BackupUnreadable(f"{failed} failed its test in {archive}")
    if expected is not None and names != expected:
        raise BackupUnreadable(f"{archive} does not hold what was written to it")


__all__ = [
    "BACKUP_NAME",
    "SET_FOLDER_COMMAND",
    "BackupCheck",
    "BackupReport",
    "Member",
    "RestoreReport",
    "check_backup",
    "members_of",
    "restore_backup",
    "write_backup",
]
