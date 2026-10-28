"""A write prepared in a mirror of the collections, then published at once
(14e, #507).

An operation's slow part - fetching, converting, crawling - runs against a
mirror of the three collections and holds no lock, so nothing it writes is
seen until it is published, and an interruption while preparing leaves the
corpus as it was. The operation runs unchanged: it is handed the mirror as
its corpus root.

**The mirror** is `.git/kennis-staging/<id>/` inside the corpus: inside
`.git` because no `git add --all .` looks there, and on the corpus's own
filesystem because a writable file is hard-linked rather than copied. A
read-only file - something kennis obtained (#514) - is copied instead,
because its mode and its removal belong to the file and not to a link, and
Windows refuses to remove or replace it at all until the mode is changed.
`atomic.make_read_only` breaks a link before sealing, for the same reason.

**What changed is found, not recorded.** Every write kennis makes is a
rename onto the path (`atomic.replace_file`), so a file the operation wrote
has a new inode; one it sealed has a new mode; one it removed is missing.
Each mirror file's inode and mode are noted when the mirror is made, and
the comparison afterwards is the operation's whole effect.

**Publishing** checks that what the operation replaced or removed is still
what it was when mirrored - otherwise another write landed meanwhile and
would be overwritten - then journals every path, places them, and commits.
A failure while placing, or a journal found at the next start, puts back
exactly the journalled paths from the commit before. Never a whole-tree
reset, which would discard a person's edit elsewhere
(`Repository.restore`).

Holding the lock that makes a publish exclusive is the caller's: the engine
takes no in-process lock.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from kennis.engine.atomic import make_writable, remove_file, remove_tree, replace_file
from kennis.engine.cancelling import past_cancelling
from kennis.engine.corpus.conversions import forget_old_conversions
from kennis.engine.corpus.document import seal_if_obtained
from kennis.engine.corpus.layout import STAGING_DIRNAME
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import PublishRefused
from kennis.engine.history.repository import Repository

_JOURNAL_FILENAME: Final = "kennis-publishing.json"

# `replace_file`'s temporary files: `mkstemp(suffix=".tmp")` in the target's
# own directory, so a process killed mid-write leaves one beside the file.
_TEMPORARY: Final = re.compile(r"^tmp[a-z0-9_]+\.tmp$")


def staging_root(corpus_root: Path) -> Path:
    return corpus_root / ".git" / STAGING_DIRNAME


def journal_path(corpus_root: Path) -> Path:
    return corpus_root / ".git" / _JOURNAL_FILENAME


@dataclass(frozen=True, slots=True)
class _Seen:
    """A file as it stood when the mirror was made: the mirror's copy or
    link, and the corpus's own file, for the precondition."""

    inode: int
    mode: int
    real: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Changes:
    """The operation's whole effect, as paths relative to the corpus root."""

    placed: tuple[str, ...] = ()
    modes: tuple[tuple[str, int], ...] = ()
    removed: tuple[str, ...] = ()
    made_directories: tuple[str, ...] = ()
    removed_directories: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (
            self.placed
            or self.modes
            or self.removed
            or self.made_directories
            or self.removed_directories
        )

    @property
    def paths(self) -> tuple[str, ...]:
        return (
            *self.placed,
            *(path for path, _ in self.modes),
            *self.removed,
        )


@dataclass(slots=True)
class Mirror:
    """One operation's mirror of the collections, and what it started as."""

    corpus_root: Path
    root: Path
    _files: dict[str, _Seen] = field(default_factory=dict)
    _directories: set[str] = field(default_factory=set)

    def changes(self) -> Changes:
        placed: list[str] = []
        modes: list[tuple[str, int]] = []
        present: set[str] = set()
        directories: set[str] = set()
        for relative, kind, status in _walk(self.root):
            if kind == "directory":
                directories.add(relative)
                continue
            present.add(relative)
            seen = self._files.get(relative)
            if seen is None or seen.inode != status.st_ino:
                placed.append(relative)
            elif seen.mode != stat.S_IMODE(status.st_mode):
                modes.append((relative, stat.S_IMODE(status.st_mode)))
        return Changes(
            placed=tuple(sorted(placed)),
            modes=tuple(sorted(modes)),
            removed=tuple(sorted(set(self._files) - present)),
            made_directories=tuple(sorted(directories - self._directories)),
            removed_directories=tuple(
                sorted(self._directories - directories, reverse=True)
            ),
        )

    def refusals(self, changes: Changes) -> list[str]:
        """What another write changed under this one while it prepared."""
        changed: list[str] = []
        for relative in changes.paths:
            seen = self._files.get(relative)
            real = self.corpus_root / relative
            if seen is None:
                if real.exists():
                    changed.append(relative)
            elif _identity(real) != seen.real:
                changed.append(relative)
        return changed

    def rebased[Value](self, value: Value) -> Value:
        """`value` with every path in the mirror named in the corpus instead:
        a path, a string that quotes one, and anything holding either."""
        return _rebased(value, str(self.root), str(self.corpus_root))

    def rebase_error(self, error: BaseException) -> None:
        """Rewrite an exception's message in place, so a refusal names the
        document the person has, not the mirror's copy."""
        error.args = tuple(
            _rebased(argument, str(self.root), str(self.corpus_root))
            for argument in error.args
        )


def make_mirror(corpus_root: Path) -> Mirror:
    """A mirror of the collections as they stand. The caller holds the
    corpus, at least to read, so the mirror is never half of a publish."""
    mirror = Mirror(
        corpus_root=corpus_root, root=staging_root(corpus_root) / uuid.uuid4().hex
    )
    try:
        _make(mirror)
    except BaseException:
        discard(mirror)
        raise
    return mirror


def discard(mirror: Mirror) -> None:
    remove_tree(mirror.root, ignore_errors=True)


@contextmanager
def mirrored(corpus_root: Path) -> Iterator[Mirror]:
    """A mirror of the collections for the length of the block; gone after
    it, whether or not it was published."""
    mirror = make_mirror(corpus_root)
    try:
        yield mirror
    finally:
        discard(mirror)


@contextmanager
def journalled(
    corpus_root: Path, operation: str, paths: Sequence[str]
) -> Iterator[None]:
    """The journal around a write that does not go through a mirror - a
    restore or a return, which git writes into the working tree itself.
    `paths` is every file the write may touch; on any failure, here or at
    the next start, they are put back as they were. From here the task runs
    to its end, cancelled or not."""
    past_cancelling()
    _write_journal(
        corpus_root,
        operation,
        Repository(corpus_root).head(),
        Changes(placed=tuple(paths)),
    )
    try:
        yield
    except BaseException:
        _roll_back(corpus_root)
        raise
    journal_path(corpus_root).unlink(missing_ok=True)


def publish(mirror: Mirror, *, operation: str, scope: str, summary: str) -> str | None:
    """Place what the operation did and commit it, or put it all back.

    The caller holds the corpus exclusively. Returns the commit, or None
    when the operation changed nothing - which writes no journal either.
    From here the task runs to its end, cancelled or not.
    """
    past_cancelling()
    changes = mirror.changes()
    if changes.empty:
        return None
    changed = mirror.refusals(changes)
    if changed:
        raise PublishRefused(
            f"another write changed {_named(changed)} while this was being "
            "prepared, so nothing was changed",
        )
    corpus_root = mirror.corpus_root
    repository = Repository(corpus_root)
    # What someone changed by hand is recorded under its own name first
    # (#525 item 3, Brian, 2026-10-21): the commit below stages with
    # `git add --all .` and would otherwise claim it. Here rather than
    # before preparing, so a write that changes nothing records nothing.
    repository.commit("record", scope="corpus", summary=RECORD_SUMMARY)
    _write_journal(corpus_root, operation, repository.head(), changes)
    try:
        _place(mirror, changes)
        commit = repository.commit(operation, scope=scope, summary=summary)
    except BaseException:
        _roll_back(corpus_root)
        raise
    journal_path(corpus_root).unlink(missing_ok=True)
    return commit


RECORD_SUMMARY: Final = "what was not yet recorded"


def recover(corpus_root: Path) -> str | None:
    """Undo a publish a killed process left half done, and clear what such a
    process leaves behind. Returns the operation undone, or None.

    Run at the service's start, before it takes any work: the owner lock
    says no other kennis is writing, so a staging folder, a `replace_file`
    temporary and git's `index.lock` are all abandoned. The last stops every
    later commit until it goes.
    """
    rolled_back: str | None = None
    if journal_path(corpus_root).is_file():
        journal = json.loads(journal_path(corpus_root).read_text(encoding="utf-8"))
        rolled_back = str(journal["operation"])
        _roll_back(corpus_root)
    remove_tree(staging_root(corpus_root), ignore_errors=True)
    forget_old_conversions(corpus_root)
    (corpus_root / ".git" / "index.lock").unlink(missing_ok=True)
    for name in COLLECTION_NAMES:
        for directory, _, files in os.walk(corpus_root / name):
            for file_name in files:
                if _TEMPORARY.match(file_name):
                    remove_file(Path(directory) / file_name, missing_ok=True)
    return rolled_back


# ---------------------------------------------------------------------------
# Making the mirror


def _make(mirror: Mirror) -> None:
    mirror.root.mkdir(parents=True)
    for relative, kind, status in _walk(mirror.corpus_root):
        source = mirror.corpus_root / relative
        target = mirror.root / relative
        if kind == "directory":
            target.mkdir(exist_ok=True)
            mirror._directories.add(relative)
            continue
        if status.st_mode & stat.S_IWUSR:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        else:
            shutil.copy2(source, target)
        made = target.stat()
        mirror._files[relative] = _Seen(
            inode=made.st_ino,
            mode=stat.S_IMODE(made.st_mode),
            real=(status.st_ino, status.st_size, status.st_mtime_ns),
        )


def _walk(root: Path) -> Iterator[tuple[str, str, os.stat_result]]:
    """Every directory and file under the collections at `root`, relative
    to it, directories before what they hold."""
    for name in COLLECTION_NAMES:
        top = root / name
        if not top.is_dir():
            continue
        yield name, "directory", top.stat()
        for directory, directories, files in os.walk(top):
            directories.sort()
            here = Path(directory)
            for child in sorted(directories):
                path = here / child
                yield path.relative_to(root).as_posix(), "directory", path.stat()
            for child in sorted(files):
                path = here / child
                yield path.relative_to(root).as_posix(), "file", path.lstat()


def _identity(path: Path) -> tuple[int, int, int] | None:
    try:
        status = path.stat()
    except FileNotFoundError:
        return None
    return status.st_ino, status.st_size, status.st_mtime_ns


# ---------------------------------------------------------------------------
# Publishing and putting back


def _write_journal(
    corpus_root: Path, operation: str, head: str | None, changes: Changes
) -> None:
    document = {
        "operation": operation,
        "head": head,
        "paths": list(changes.paths),
        "made_directories": list(changes.made_directories),
    }
    replace_file(journal_path(corpus_root), json.dumps(document, indent=2) + "\n")


def _place(mirror: Mirror, changes: Changes) -> None:
    corpus_root = mirror.corpus_root
    for relative in changes.made_directories:
        (corpus_root / relative).mkdir(parents=True, exist_ok=True)
    for relative in changes.placed:
        target = corpus_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        make_writable(target)
        os.replace(mirror.root / relative, target)
    for relative, mode in changes.modes:
        (corpus_root / relative).chmod(mode)
    for relative in changes.removed:
        remove_file(corpus_root / relative, missing_ok=True)
    for relative in changes.removed_directories:
        directory = corpus_root / relative
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _roll_back(corpus_root: Path) -> None:
    """Put every journalled path back as it was at the journalled commit,
    then the commit itself; nothing else in the working tree is touched."""
    journal = json.loads(journal_path(corpus_root).read_text(encoding="utf-8"))
    head = journal["head"]
    repository = Repository(corpus_root)
    for relative in journal["paths"]:
        if head is not None and repository.show(head, relative) is not None:
            repository.restore(relative, commit=head)
            path = corpus_root / relative
            collection = relative.split("/", 1)[0]
            if path.suffix == ".md" and collection in COLLECTION_NAMES:
                seal_if_obtained(path, collection=collection)
        else:
            remove_file(corpus_root / relative, missing_ok=True)
    for relative in sorted(journal["made_directories"], reverse=True):
        directory = corpus_root / relative
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if head is not None:
        # Always, not only when HEAD moved: a return stages what it checks
        # out, and those entries would outlive their files.
        repository.move_head(head)
    journal_path(corpus_root).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Paths in what comes back


def _rebased[Value](value: Value, mirror: str, corpus: str) -> Value:
    rebased: object
    if isinstance(value, Path):
        text = str(value)
        rebased = Path(corpus + text[len(mirror) :]) if _under(text, mirror) else value
    elif isinstance(value, str):
        rebased = value.replace(mirror, corpus)
    elif isinstance(value, tuple):
        items = [_rebased(item, mirror, corpus) for item in value]
        # A named tuple takes its fields as arguments, a plain one an iterable.
        rebased = type(value)(*items) if hasattr(value, "_fields") else tuple(items)
    elif isinstance(value, list):
        rebased = [_rebased(item, mirror, corpus) for item in value]
    elif isinstance(value, Mapping):
        rebased = {
            _rebased(key, mirror, corpus): _rebased(item, mirror, corpus)
            for key, item in value.items()
        }
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        rebased = dataclasses.replace(
            value,
            **{
                one.name: _rebased(getattr(value, one.name), mirror, corpus)
                for one in dataclasses.fields(value)
                if one.init
            },
        )
    else:
        rebased = value
    # Each branch rebuilds the type it was given, which the checker cannot
    # follow through `isinstance`.
    return cast(Value, rebased)


def _under(text: str, root: str) -> bool:
    return text == root or text.startswith(root + os.sep)


def _named(paths: list[str]) -> str:
    return paths[0] if len(paths) == 1 else f"{paths[0]} and {len(paths) - 1} more"


__all__ = [
    "Changes",
    "Mirror",
    "discard",
    "journal_path",
    "journalled",
    "make_mirror",
    "mirrored",
    "publish",
    "recover",
    "staging_root",
]
