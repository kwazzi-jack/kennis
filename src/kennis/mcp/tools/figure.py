"""The `figure` tool: an image a document links, as an image (#642).

`read` answers a passage's text, in which a figure is a link and a
caption. This answers the image. **A tool of its own, and never part of
`read`** (Brian, 2026-11-12): an image is paid for in an agent's context
by its size, so reading text must not bring one unless it was asked for.

What may be asked for, what is fetched and from where are `kennis/figures.py`'s
rules, which the service applies: only an image the document's own
markdown links, kept beside it or held at a site the user named.

**Batched, as `read` is.** One figure that fails is a line saying why, and
the others are still answered.
"""

from __future__ import annotations

import base64
from typing import Final

from fastmcp.utilities.types import Image

from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError

# How many figures one call answers. Each is an image in the agent's
# context, so fewer than `read`'s passages.
_MAX_FIGURES: Final = 4

_NOTHING: Final = "no figures named"


def figure(document_id: str, names: list[str]) -> list[str | Image]:
    """Look at figures of a document in `notes`, `literature` or `docs`.

    `read` shows a figure as a link and its caption, such as
    `![](3f9a1c0b7d2e4a68.jpg)` followed by `Figure 2. ...`. Pass the
    document's `document_id` and, in `names`, the text between the
    parentheses of each figure you want, copied exactly: a file name, or a
    full `https://` address. At most 4 a call.

    Call this only when seeing the figure matters to the answer - a plot
    whose values the text does not give, a diagram a caption refers to. An
    image costs far more to read than the passage around it.

    A figure kept with the document is answered at once. One held at a web
    site is fetched only when the user has named that site as trusted, and
    may take some seconds; when they have not, the answer says so and names
    the setting, which is theirs to change, not yours. A document converted
    before images were kept has links and no images.

    Each figure is answered as a line naming it and then the image; one
    that cannot be had is a line saying why, and does not cost the others.
    """
    if not names:
        return [_NOTHING]
    if len(names) > _MAX_FIGURES:
        return [
            f"{len(names)} figures is more than one call answers. "
            f"Ask for at most {_MAX_FIGURES}."
        ]
    corpus_root = existing_corpus().corpus_root
    answered: list[str | Image] = []
    for name in names:
        try:
            found = api.figure(corpus_root, document_id, name)
        except KennisError as error:
            resolution = f" Run `{error.resolution}`." if error.resolution else ""
            answered.append(f"{name}: {error}.{resolution}")
            continue
        answered.append(f"{name}  ({found.origin}, {found.media_type})")
        answered.append(
            Image(
                data=base64.b64decode(found.data),
                format=found.media_type.removeprefix("image/"),
            )
        )
    return answered


__all__ = ["figure"]
