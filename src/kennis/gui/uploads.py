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

**Each file is written as its bytes arrive, and closed before the next
begins** (#11). Starlette's form refuses more than 1000 files, which an
Obsidian vault chosen with the folder button passes, and holds every part
past a megabyte open as a temporary file until the whole form is read, which
a folder of a thousand PDFs passes the limit on open files with. So a form
that carries files is read here, with no limit on their count or size:
they are the reader's own files, sent by a window that holds the token.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, BinaryIO, Final

import anyio.to_thread
from fastapi import Depends
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request

from kennis.engine.errors import KennisError
from kennis.gui import words

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

# Where every session's uploads go, each in a folder of its own.
_PREFIX: Final = "kennis-upload-"

# What a typed field may hold, as Starlette allowed: far past anything typed,
# and a bound on what is kept in memory.
FIELD_LIMIT: Final = 1024 * 1024


class FormUnread(KennisError):
    """A posted form that could not be read: not a form, or a typed field
    past `FIELD_LIMIT`. Nothing was started."""

    default_message = words.FORM_UNREAD


@dataclass(frozen=True, slots=True)
class Staged:
    """What one field's uploads became on disk."""

    # What to add: each file sent alone, and each uploaded folder once.
    paths: list[Path] = field(default_factory=list)
    # Every file written, with the name it was sent under.
    names: dict[Path, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Received:
    """A posted form: its typed fields, and each file field's uploads."""

    fields: FormData
    files: dict[str, Staged]

    def staged(self, name: str) -> Staged:
        """The files sent under `name`, or none."""
        return self.files.get(name, Staged())

    def discard(self, name: str) -> None:
        """Remove what was sent under `name` now, rather than at exit."""
        for path in self.staged(name).paths:
            shutil.rmtree(path.parent, ignore_errors=True)


async def received(request: Request) -> Received:
    """Read a posted form, writing each file to disk as it arrives.

    The parse runs on a worker thread a chunk at a time, because it writes,
    and the event loop also streams a running job's progress. A file input
    left empty still posts one part with no name; it is read and dropped,
    so a form whose upload was not used adds what was typed.
    """
    kind, options = parse_options_header(request.headers.get("content-type", ""))
    if kind != b"multipart/form-data":
        # A tab with no file input posts its fields encoded in the body,
        # which carries no file to count or hold open.
        return Received(fields=await request.form(), files={})
    boundary = options.get(b"boundary")
    if not boundary:
        raise FormUnread()
    reader = _Reader()
    callbacks: MultipartCallbacks = {
        "on_part_begin": reader.begin_part,
        "on_header_field": reader.header_name,
        "on_header_value": reader.header_value,
        "on_header_end": reader.end_header,
        "on_headers_finished": reader.open_part,
        "on_part_data": reader.part_data,
        "on_part_end": reader.end_part,
    }
    parser = MultipartParser(boundary, callbacks)
    try:
        async for chunk in request.stream():
            await anyio.to_thread.run_sync(parser.write, chunk)
    except (FormParserError, _FieldTooLong) as error:
        raise FormUnread() from error
    finally:
        # Cut short - refused, or the window gone - a file being written is
        # closed here, and its folder stays for `atexit` to remove.
        reader.close_open_file()
    return Received(fields=FormData(reader.fields), files=reader.staged)


# A route's form, files written, as a parameter: `posted: PostedWithFiles`.
type PostedWithFiles = Annotated[Received, Depends(received)]


class _FieldTooLong(Exception):
    """Raised inside the parser's callback, and read as `FormUnread`."""


class _Reader:
    """The parser's callbacks: one part at a time, a file written as it
    comes and a typed field kept as text."""

    def __init__(self) -> None:
        self.fields: list[tuple[str, str | UploadFile]] = []
        self.staged: dict[str, Staged] = {}
        self._roots: dict[str, Path] = {}
        self._header_name = b""
        self._header_value = b""
        self._disposition = b""
        self._name = ""
        self._parts: tuple[str, ...] = ()
        self._is_file = False
        self._text = bytearray()
        self._file: BinaryIO | None = None

    def begin_part(self) -> None:
        self._disposition = b""
        self._text = bytearray()

    def header_name(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def end_header(self) -> None:
        if self._header_name.lower() == b"content-disposition":
            self._disposition = self._header_value
        self._header_name = b""
        self._header_value = b""

    def open_part(self) -> None:
        _, options = parse_options_header(self._disposition)
        self._name = _decoded(options.get(b"name", b""))
        self._is_file = b"filename" in options
        self._parts = _parts_of(_decoded(options.get(b"filename", b"")))
        if not (self._is_file and self._parts):
            return
        root = self._roots.get(self._name)
        if root is None:
            root = Path(tempfile.mkdtemp(prefix=_PREFIX))
            atexit.register(shutil.rmtree, root, ignore_errors=True)
            self._roots[self._name] = root
            self.staged[self._name] = Staged()
        target = root.joinpath(*self._parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._file = target.open("wb")
        staged = self.staged[self._name]
        staged.names[target] = "/".join(self._parts)
        top = root / self._parts[0]
        if top not in staged.paths:
            staged.paths.append(top)

    def part_data(self, data: bytes, start: int, end: int) -> None:
        if self._file is not None:
            self._file.write(data[start:end])
        elif not self._is_file:
            if len(self._text) + end - start > FIELD_LIMIT:
                raise _FieldTooLong()
            self._text += data[start:end]

    def end_part(self) -> None:
        if self._is_file:
            self.close_open_file()
        else:
            self.fields.append((self._name, _decoded(bytes(self._text))))

    def close_open_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def _decoded(raw: bytes) -> str:
    """As Starlette decodes a part: UTF-8, which every browser sends, and
    Latin-1 for bytes that are not, so a name is never refused for it."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


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


__all__ = [
    "FIELD_LIMIT",
    "FormUnread",
    "PostedWithFiles",
    "Received",
    "Staged",
    "received",
]
