"""`kennis://` links: a document and a chunk, named without an address.

The window's own address cannot be cited: its port is chosen when the
service starts and every request carries a token made at that start, so an
address written today is dead tomorrow, and one carrying the token would put
it in a transcript sent to a model provider (#569). A link names only what
is cited - `kennis://open/<document id>/<chunk>` - and `kennis open` turns it
into the address of the service running when it is clicked.

Beside `context.py` because the command line, the MCP server and the
service all need it, and none owns it.

**Read strictly.** What follows `open/` is a document identifier and a chunk
number and nothing else - no query, no fragment, no further path - because a
link arrives from whatever program it was clicked in, and the operating
system runs kennis with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, urlencode

from kennis.engine.errors import KennisError
from kennis.engine.scheme import SCHEME

_PREFIX: Final = f"{SCHEME}://open/"

# An identifier is ten characters of lower-case letters and digits
# (`engine/corpus/ids.py`); any length is read, so a link stays readable if
# that changes, and nothing else is, because the identifier is put into a
# path of the window's address.
_LINK: Final = re.compile(r"(?P<id>[a-z0-9]+)(?:/(?P<chunk>[0-9]+))?/?")


class NotAKennisLink(KennisError):
    """Text given as a link that is not one kennis writes."""

    default_message = (
        "this is not a kennis link, which reads kennis://open/<document>/<chunk>"
    )


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """What a link names: a document, and the chunk to mark, if any."""

    document_id: str
    chunk: int | None


def link_to(document_id: str, chunk: int | None) -> str:
    """The link to a document, at a chunk when one is given."""
    if chunk is None:
        return f"{_PREFIX}{document_id}"
    return f"{_PREFIX}{document_id}/{chunk}"


def is_a_link(text: str) -> bool:
    """Whether `text` is offered as a link, rather than as a handle."""
    return text.lower().startswith(f"{SCHEME}:")


def target_of(text: str) -> LinkTarget:
    """What the link `text` names, or `NotAKennisLink`.

    The scheme is read without regard to case, as a URL's scheme is: a
    desktop may hand the handler the link as typed or lower-cased.
    """
    if not text.lower().startswith(_PREFIX):
        raise NotAKennisLink()
    matched = _LINK.fullmatch(text[len(_PREFIX) :])
    if matched is None:
        raise NotAKennisLink()
    chunk = matched.group("chunk")
    return LinkTarget(
        document_id=matched.group("id"),
        chunk=None if chunk is None else int(chunk),
    )


def window_address(
    service: str, collection: str, document_id: str, chunk: int | None, token: str
) -> str:
    """Where the running service's window shows the document, at the chunk.

    The chunk rides in the query string, which the page marks it by, and in
    the fragment, which the browser scrolls to, as a search hit's link does
    (`gui/pages.py::_href`). The token is in the query, as `kennis gui` gives
    it, and the window moves it to a cookie.
    """
    named: dict[str, str] = {"token": token}
    fragment = ""
    if chunk is not None:
        named = {"chunk": str(chunk), **named}
        fragment = f"#chunk-{chunk}"
    path = f"document/{quote(collection)}/{quote(document_id)}"
    return f"{service.rstrip('/')}/{path}?{urlencode(named)}{fragment}"


__all__ = [
    "SCHEME",
    "LinkTarget",
    "NotAKennisLink",
    "is_a_link",
    "link_to",
    "target_of",
    "window_address",
]
