"""`kennis://` links: a document and a chunk, named without an address.

The window's own address cannot be cited: its port is chosen when the
service starts and every request carries a token made at that start, so an
address written today is dead tomorrow, and one carrying the token would put
it in a transcript sent to a model provider (#569). A link names only what
is cited - `kennis://open/<document id>/<chunk>` - and `kennis open` turns it
into the address of the service running when it is clicked.

A context passage has no identifier: it is a file in a project's
`.context/`, so its link names where it is (#623) -
`kennis://context/<project>/<chunk>?path=<path>`, each part percent-encoded,
because a project's name may hold `/` (#512) and a path a space. The project
is this machine's name for it (`kennis context list`), so such a link opens
where that project is known by that name, and a renamed file breaks it.

Beside `context.py` because the command line, the MCP server and the
service all need it, and none owns it.

**Read strictly.** What follows `open/` is a document identifier and a chunk
number and nothing else - no query, no fragment, no further path - because a
link arrives from whatever program it was clicked in, and the operating
system runs kennis with it. The context form takes exactly one query
key, `path`, which must be relative and climb nowhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from kennis.engine.errors import KennisError
from kennis.engine.scheme import SCHEME

_PREFIX: Final = f"{SCHEME}://open/"
_CONTEXT: Final = "context"
_PATH_KEY: Final = "path"
_CHUNK: Final = re.compile(r"[0-9]+")
# A Windows drive, which would make a path absolute there; a colon anywhere
# else is an ordinary character in a Linux filename.
_DRIVE: Final = re.compile(r"[A-Za-z]:")

# An identifier is ten characters of lower-case letters and digits
# (`engine/corpus/ids.py`); any length is read, so a link stays readable if
# that changes, and nothing else is, because the identifier is put into a
# path of the window's address.
_LINK: Final = re.compile(r"(?P<id>[a-z0-9]+)(?:/(?P<chunk>[0-9]+))?/?")


class NotAKennisLink(KennisError):
    """Text given as a link that is not one kennis writes."""

    default_message = (
        "this is not a kennis link, which reads kennis://open/<document>/<chunk> "
        "or kennis://context/<project>/<chunk>?path=<path>"
    )


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """What a corpus link names: a document, and the chunk to mark, if any."""

    document_id: str
    chunk: int | None


@dataclass(frozen=True, slots=True)
class ContextTarget:
    """What a context link names: a file in a project's bundle, by the
    project's name here and its path in the bundle, and a chunk."""

    project: str
    path: str
    chunk: int | None


type Target = LinkTarget | ContextTarget


def link_to(document_id: str, chunk: int | None) -> str:
    """The link to a document, at a chunk when one is given."""
    if chunk is None:
        return f"{_PREFIX}{document_id}"
    return f"{_PREFIX}{document_id}/{chunk}"


def context_link(project: str, path: str, chunk: int | None) -> str:
    """The link to a file in the project's bundle, at a chunk when given."""
    named = quote(project, safe="")
    at = "" if chunk is None else f"/{chunk}"
    return f"{SCHEME}://{_CONTEXT}/{named}{at}?{urlencode({_PATH_KEY: path})}"


def is_a_link(text: str) -> bool:
    """Whether `text` is offered as a link, rather than as a handle."""
    return text.lower().startswith(f"{SCHEME}:")


def target_of(text: str) -> Target:
    """What the link `text` names, or `NotAKennisLink`.

    The scheme is read without regard to case, as a URL's scheme is: a
    desktop may hand the handler the link as typed or lower-cased.
    """
    lowered = text.lower()
    if lowered.startswith(f"{SCHEME}://{_CONTEXT}/"):
        return _context_target(text)
    if not lowered.startswith(_PREFIX):
        raise NotAKennisLink()
    matched = _LINK.fullmatch(text[len(_PREFIX) :])
    if matched is None:
        raise NotAKennisLink()
    chunk = matched.group("chunk")
    return LinkTarget(
        document_id=matched.group("id"),
        chunk=None if chunk is None else int(chunk),
    )


def _context_target(text: str) -> ContextTarget:
    parts = urlsplit(text)
    if parts.fragment or "#" in text:
        raise NotAKennisLink()
    segments = parts.path.split("/")
    # `urlsplit` puts the verb in the network location: what is left is
    # `/<project>` or `/<project>/<chunk>`.
    if segments[0] != "" or len(segments) not in (2, 3):
        raise NotAKennisLink()
    owner = unquote(segments[1])
    chunk: int | None = None
    if len(segments) == 3:
        if _CHUNK.fullmatch(segments[2]) is None:
            raise NotAKennisLink()
        chunk = int(segments[2])
    try:
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise NotAKennisLink() from error
    if len(query) != 1 or query[0][0] != _PATH_KEY:
        raise NotAKennisLink()
    path = query[0][1]
    if not _is_a_relative_path(path) or not _is_a_name(owner):
        raise NotAKennisLink()
    return ContextTarget(project=owner, path=path, chunk=chunk)


def _is_a_name(text: str) -> bool:
    return bool(text) and not any(ord(character) < 32 for character in text)


def _is_a_relative_path(text: str) -> bool:
    """Whether `text` is a path inside a folder: relative, in `/`
    segments, none of them empty, `.` or `..`, and no backslash or control
    character, and no drive, so that it climbs out on no platform."""
    if not _is_a_name(text) or "\\" in text or _DRIVE.match(text):
        return False
    return all(segment not in ("", ".", "..") for segment in text.split("/"))


def window_path(collection: str, document_id: str, chunk: int | None) -> str:
    """The window's path for the document, at the chunk, with no token.

    The chunk rides in the query string, which the page marks it by, and in
    the fragment, which the browser scrolls to, as a search hit's link does
    (`gui/pages.py::_href`).
    """
    path = f"/document/{quote(collection)}/{quote(document_id)}"
    if chunk is None:
        return path
    return f"{path}?{urlencode({'chunk': str(chunk)})}#chunk-{chunk}"


def context_window_path(project: str, path: str, chunk: int | None) -> str:
    """The window's path for a file in the project's bundle, at the chunk
    (`gui/routes/documents.py::serve_bundle_document`)."""
    query = {"project": project}
    return _with_chunk(f"/bundle/{quote(path)}", query, chunk)


def _with_chunk(route: str, query: dict[str, str], chunk: int | None) -> str:
    if chunk is not None:
        query = {**query, "chunk": str(chunk)}
    asked = f"?{urlencode(query)}" if query else ""
    anchor = "" if chunk is None else f"#chunk-{chunk}"
    return f"{route}{asked}{anchor}"


def window_path_of(target: ContextTarget) -> str:
    """The window's path for what a context link names."""
    return context_window_path(target.project, target.path, target.chunk)


def window_address(service: str, window: str, token: str) -> str:
    """Where the running service's window shows `window`, a path of the
    window's own: on the service's address, with the token in the query, as
    `kennis gui` gives it, which the window moves to a cookie."""
    path, _, fragment = window.partition("#")
    joiner = "&" if "?" in path else "?"
    address = f"{service.rstrip('/')}{path}{joiner}{urlencode({'token': token})}"
    return f"{address}#{fragment}" if fragment else address


def is_a_document_id(text: str) -> bool:
    """Whether `text` has the shape of a document identifier, so that it can
    be put into a path of the window's address."""
    return re.fullmatch(r"[a-z0-9]+", text) is not None


__all__ = [
    "SCHEME",
    "ContextTarget",
    "LinkTarget",
    "NotAKennisLink",
    "Target",
    "context_link",
    "context_window_path",
    "is_a_document_id",
    "is_a_link",
    "link_to",
    "target_of",
    "window_address",
    "window_path",
    "window_path_of",
]
