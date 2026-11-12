"""What a figure is, and one figure for an agent (#642, #660).

Beside `context.py`, because the window and the MCP server both ask what a
figure is and neither owns the answer: `held_figure` is the one rule for an
image kept beside its document, and `figure_of` is what the `figure` tool
answers with.

**An agent can ask only for what the document already links as an image.**
That is what keeps `figure_of` from being a way to read any file or to
fetch any address: the name is looked for in the document's own markdown
before anything else is done with it.

**A figure held at a site is fetched only from a host the reader named**
(`figures.trusted_hosts`), over HTTPS, as a document's page loads it:
fetching one tells its host which document is being read, and that is the
reader's decision, made once per host. Fetched through `courtesy`, so the
host's robots.txt and its `Crawl-delay` hold, and kept under the state
folder, never in the corpus.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from urllib.parse import unquote, urlparse

import httpx

from kennis.context import Context
from kennis.engine.atomic import replace_file
from kennis.engine.bounded import TooLarge
from kennis.engine.corpus.images import IMAGE_MEDIA_TYPES, linked_images
from kennis.engine.corpus.layout import WRAPPED_DOCUMENT_FILENAME, relative_to_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.courtesy import Disallowed, get_politely
from kennis.engine.errors import InputError
from kennis.engine.settings import figure_hosts, load_settings, state_dir
from kennis.finding import resolve_document
from kennis.publishing import reading
from kennis.render.html import is_trusted

# The most one figure may hold. An answer goes into an agent's context,
# where an image is paid for by its size; a figure MinerU cuts from a paper
# is tens to hundreds of kilobytes.
MAX_FIGURE_BYTES: Final = 3 * 1024 * 1024

_USER_AGENT: Final = "kennis-figure-fetch"
_TIMEOUT_SECONDS: Final = 30.0
_CACHE_FOLDER: Final = "figures"
_REMOTE_SCHEMES: Final = frozenset({"http", "https"})

type Origin = Literal["kept", "fetched"]


@dataclass(frozen=True, slots=True)
class Figure:
    """One image a document links. `data` is base64 text, because a value
    that crosses to a client is JSON and carries no bytes."""

    name: str
    media_type: str
    data: str
    origin: Origin


def held_figure(corpus_root: Path, path: str) -> Path | None:
    """The image file at `path`, relative to the corpus, or None when it is
    not a figure: a raster image that is a document's own asset.

    Every part of the path is an ordinary name inside a collection, so
    nothing is reached by climbing and nothing under `.git` or the index.
    Raster formats only, because an SVG can carry script and this is served
    to a page holding the reader's token.

    No backslash anywhere: on Windows it separates folders inside what
    this function took for one name, so a name written with one and
    `..` climbed past every check here. And the file itself, links
    followed, is inside the corpus, as `kept_images` requires of what a
    conversion links.
    """
    parts = path.split("/")
    if parts[0] not in COLLECTION_NAMES or "\\" in path:
        return None
    if any(not part or part.startswith(".") for part in parts):
        return None
    if PurePosixPath(path).suffix.lower() not in IMAGE_MEDIA_TYPES:
        return None
    candidate = corpus_root.joinpath(*parts)
    if not (candidate.parent / WRAPPED_DOCUMENT_FILENAME).is_file():
        return None
    if not candidate.is_file():
        return None
    if not candidate.resolve().is_relative_to(corpus_root.resolve()):
        return None
    return candidate


def http_client() -> httpx.Client:
    """The client a figure is fetched with. A function, so a test answers
    the request itself."""
    return httpx.Client(headers={"User-Agent": _USER_AGENT}, follow_redirects=True)


def figure_of(context: Context, handle: str, name: str) -> Figure:
    """The figure `name` of the document `handle`, where `name` is a link
    target exactly as the document's markdown writes it.

    Raises `DocumentNotFound` as any read does, and `InputError` for a name
    the document does not link, an image that was not kept, a host the
    reader has not named, an answer that is not an image, and one over
    `MAX_FIGURE_BYTES`.
    """
    kept = _kept(context, handle, name)
    if kept is not None:
        return kept
    # Outside the corpus's shared hold: a host's `Crawl-delay` is a wait of
    # up to fifteen seconds, and a write must not wait behind it.
    return _fetched(name)


@reading
def _kept(context: Context, handle: str, name: str) -> Figure | None:
    """The figure when it is kept beside the document; None when `name` is
    a remote address the document links, for the caller to fetch."""
    _, document = resolve_document(context, handle, None)
    if name not in linked_images(document.body):
        raise InputError(
            f"'{document.frontmatter.title}' does not link '{name}' as an image",
            resolution=None,
        )
    if urlparse(name).scheme in _REMOTE_SCHEMES:
        return None
    path = (
        None
        if document.wrapper_dir is None
        else held_figure(
            context.corpus_root,
            f"{relative_to_corpus(document.wrapper_dir, context.corpus_root)}"
            f"/{unquote(name)}",
        )
    )
    if path is None:
        raise InputError(
            f"'{name}' was not kept: the document was converted before images "
            "were kept, or the image was removed",
            resolution=None,
        )
    size = path.stat().st_size
    if size > MAX_FIGURE_BYTES:
        raise _too_large(name, size)
    return _figure(
        name, IMAGE_MEDIA_TYPES[path.suffix.lower()], path.read_bytes(), "kept"
    )


def _fetched(address: str) -> Figure:
    """A figure held at a site: from what was kept of an earlier fetch, or
    fetched now. Trust is asked first either way, so a host taken off the
    list is not answered for from the cache."""
    hosts = figure_hosts(load_settings().figures.trusted_hosts)
    if not is_trusted(address, hosts):
        raise _untrusted(address, hosts)
    stem = hashlib.sha256(address.encode("utf-8")).hexdigest()
    folder = state_dir() / _CACHE_FOLDER
    content, kind = folder / stem, folder / f"{stem}.type"
    if content.is_file() and kind.is_file():
        return _figure(
            address,
            kind.read_text(encoding="utf-8").strip(),
            content.read_bytes(),
            "fetched",
        )
    with http_client() as client:
        try:
            response = get_politely(
                client,
                address,
                user_agent=_USER_AGENT,
                timeout=_TIMEOUT_SECONDS,
                limit=MAX_FIGURE_BYTES,
            )
        except Disallowed as error:
            raise InputError(str(error), resolution=None) from error
        except TooLarge as error:
            raise InputError(
                f"'{address}' is more than {MAX_FIGURE_BYTES} bytes, the most "
                "one figure may be",
                resolution=None,
            ) from error
        except httpx.HTTPError as error:
            raise InputError(
                f"'{address}' could not be fetched: {error}", resolution=None
            ) from error
    if response.status_code != httpx.codes.OK:
        raise InputError(
            f"'{address}' could not be fetched: its host answered "
            f"{response.status_code}",
            resolution=None,
        )
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in IMAGE_MEDIA_TYPES.values():
        raise InputError(
            f"'{address}' is not an image kennis shows: its host answered "
            f"'{media_type or 'no content type'}'",
            resolution=None,
        )
    # The type last: a figure is answered from the cache only when both
    # files are there.
    replace_file(content, response.content)
    replace_file(kind, f"{media_type}\n")
    return _figure(address, media_type, response.content, "fetched")


def _figure(name: str, media_type: str, content: bytes, origin: Origin) -> Figure:
    return Figure(
        name=name,
        media_type=media_type,
        data=base64.b64encode(content).decode("ascii"),
        origin=origin,
    )


def _too_large(name: str, size: int) -> InputError:
    return InputError(
        f"'{name}' is {size} bytes, more than {MAX_FIGURE_BYTES}, the most one "
        "figure may be",
        resolution=None,
    )


def _untrusted(address: str, hosts: frozenset[str]) -> InputError:
    """Why a remote figure was not fetched, and the command that changes it.

    The command names every host already trusted beside the new one,
    because `config set` replaces the value. For plain HTTP there is no
    command: no setting makes kennis fetch it.
    """
    parsed = urlparse(address)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return InputError(
            f"'{address}' is not fetched: kennis fetches a figure over HTTPS only",
            resolution=None,
        )
    wanted = " ".join(sorted(hosts | {host}))
    return InputError(
        f"'{address}' is not fetched: {host} is not among the sites whose "
        "figures load without asking. Fetching a figure tells its site which "
        "document is being read, so naming the site is for the user to decide",
        resolution=f'kennis config set figures.trusted_hosts "{wanted}"',
    )


__all__ = [
    "MAX_FIGURE_BYTES",
    "Figure",
    "figure_of",
    "held_figure",
    "http_client",
]
