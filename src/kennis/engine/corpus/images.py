"""Which of a conversion's image files are kept, and under what name.

A converter writes its images into a directory beside its markdown and
links them from it. kennis stores the markdown, so until this existed
every link pointed at a file that went with the converter's temporary
directory (#134).

**What the markdown links is kept, and nothing else.** MinerU wrote 129
image files for one paper and linked 5; the rest were crops of equations
and tables that nothing refers to. For a paper with no figure it wrote 55
and linked none (measured 2026-11-11).

**An image is named by its own content**: the first sixteen hexadecimal
characters of its sha256, and its suffix. Not the converter's name, which
for MinerU is 64 characters that are not a hash of the file, and for
another converter is a page and a counter. Sixteen rather than sixty-four
because an add is prepared in a mirror at
`<corpus>/.git/kennis-staging/<32 hex>/<collection>/<group>/<title>/`, and
on Windows the longer name put a paper with a long title past 260
characters.

**One path component, so an image sits directly in its document's
directory.** Everything that handles a document with assets treats that
directory as one level - `history/freshness.py::document_of` derives a
changed asset's document from its parent directory, because a deleted file
cannot be examined - so a subdirectory of images would be counted as a
document of its own.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

# Raster formats only. An SVG is a document that can carry script, and the
# window will one day serve these files to a browser.
IMAGE_MEDIA_TYPES: Final[Mapping[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(IMAGE_MEDIA_TYPES)

_NAME_LENGTH: Final = 16

# `![alt](target)`, the target without a space: no converter measured writes
# a title after it, and a target holding one is left as written.
_IMAGE_LINK: Final = re.compile(r"!\[(?P<alt>[^\]\n]*)\]\((?P<target>[^()\s]+)\)")


def kept_images(markdown: str, directory: Path) -> tuple[str, dict[str, bytes]]:
    """`markdown` with each image it links from `directory` renamed, and
    those images' bytes under their new names.

    `directory` is where the markdown was written, which is what its
    relative links are relative to. A link is followed only to a regular
    file **inside** `directory`: the markdown is a converter's output, and
    must not be able to name a file of the person's and have it copied into
    the corpus. A link that is not kept - a remote address, a missing file,
    a path that leaves the directory, a suffix that is not a raster image -
    is left exactly as written.
    """
    root = directory.resolve()
    images: dict[str, bytes] = {}

    def renamed(match: re.Match[str]) -> str:
        content = _linked_image(match["target"], root)
        if content is None:
            return match.group()
        suffix = Path(match["target"]).suffix.lower()
        name = hashlib.sha256(content).hexdigest()[:_NAME_LENGTH] + suffix
        images[name] = content
        return f"![{match['alt']}]({name})"

    return _IMAGE_LINK.sub(renamed, markdown), images


def _linked_image(target: str, root: Path) -> bytes | None:
    """The bytes of the image `target` names under `root`, or None when it
    is not one kennis keeps.

    A remote address needs no rule of its own: it names no file under
    `root`, so it is not kept for the reason a missing file is not.
    """
    if Path(target).suffix.lower() not in IMAGE_SUFFIXES:
        return None
    try:
        # Resolved before it is compared, so neither `..` nor a symbolic
        # link the converter left can lead out of its own directory.
        path = (root / target).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


__all__ = ["IMAGE_MEDIA_TYPES", "IMAGE_SUFFIXES", "kept_images"]
