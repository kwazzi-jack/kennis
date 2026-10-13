"""Files sent from the window, put where an add can read them.

**The browser's own file picker, not one kennis draws.** It is the native
dialog of the computer the reader sits at - Finder, Explorer, the desktop's
own - and what it chose arrives as bytes through the same connection as the
page. So it works the same when kennis runs on that computer and when it
runs elsewhere behind `ssh -L`, where a dialog opened by kennis would open
on a screen nobody is looking at (#420).

An add reads paths, so each file is written into a folder of its own in the
system's temporary directory - not kennis's state directory, whose files an
add refuses as kennis's own - keeping the folders an uploaded folder had.
The folder lasts the session, so a refusal's repair can still name the file,
and is removed when kennis stops.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Final, Protocol

# Where every session's uploads go, each in a folder of its own.
_PREFIX: Final = "kennis-upload-"


class Upload(Protocol):
    """One file part of a posted form, as Starlette hands it over."""

    @property
    def filename(self) -> str | None: ...

    @property
    def file(self) -> BinaryIO: ...


@dataclass(frozen=True, slots=True)
class Staged:
    """What an upload became on disk."""

    # What to add: each file sent alone, and each uploaded folder once.
    paths: list[Path] = field(default_factory=list)
    # Every file written, with the name it was sent under.
    names: dict[Path, str] = field(default_factory=dict)


def staged(uploads: Sequence[Upload]) -> Staged:
    """Write `uploads` to a new folder and say what to add from it.

    A file input left empty still posts one part with no name; it is
    skipped, so a form whose upload was not used adds what was typed.
    Every part is closed here, used or not: each is a spooled temporary
    file the form left open.
    """
    try:
        return _written(uploads)
    finally:
        for upload in uploads:
            upload.file.close()


def _written(uploads: Sequence[Upload]) -> Staged:
    sent = [(upload, _parts_of(upload.filename or "")) for upload in uploads]
    sent = [(upload, parts) for upload, parts in sent if parts]
    if not sent:
        return Staged()
    root = Path(tempfile.mkdtemp(prefix=_PREFIX))
    atexit.register(shutil.rmtree, root, ignore_errors=True)

    result = Staged()
    for upload, parts in sent:
        target = root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as written:
            shutil.copyfileobj(upload.file, written)
        result.names[target] = "/".join(parts)
        top = root / parts[0]
        if top not in result.paths:
            result.paths.append(top)
    return result


def _parts_of(filename: str) -> tuple[str, ...]:
    """The folders and name a file was sent under, safe to join to a root.

    A browser sends a folder's files as `folder/sub/name.pdf`. Anything that
    would climb out of the root or name another place - `..`, an absolute
    path, a Windows drive - is dropped rather than followed, because the
    name is the sender's to choose.
    """
    parts = filename.replace("\\", "/").split("/")
    return tuple(
        part
        for part in parts
        if part not in ("", ".", "..") and not (len(part) == 2 and part[1] == ":")
    )


__all__ = ["Staged", "Upload", "staged"]
