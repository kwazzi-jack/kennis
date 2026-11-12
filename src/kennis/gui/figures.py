"""Which files the window serves as figures, and at what address (#642).

A conversion keeps the images a document's markdown links, directly in the
document's directory beside `content.md` (#134). **One rule says what a
figure is, and both the page and the route ask it**: a page is given an
address only for a file the route will answer, so a reference with no file
is drawn as a placeholder and never as a broken image, and the route
answers nothing a page would not have drawn.

Addressed by path rather than by the document's identifier: finding a
document by identifier reads every document of its collection, and a paper
has some tens of figures, each its own request.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import quote

from kennis.engine.corpus.images import IMAGE_MEDIA_TYPES
from kennis.engine.corpus.layout import WRAPPED_DOCUMENT_FILENAME
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.render.html import FigureAddress

FIGURE_ROUTE = "/figure"


def held_figure(corpus_root: Path, path: str) -> Path | None:
    """The image file at `path`, relative to the corpus, or None when it is
    not a figure: a raster image that is a document's own asset.

    Every part of the path is an ordinary name inside a collection, so
    nothing is reached by climbing and nothing under `.git` or the index.
    Raster formats only, because an SVG can carry script and this is served
    to a page holding the reader's token.
    """
    parts = path.split("/")
    if parts[0] not in COLLECTION_NAMES:
        return None
    if any(not part or part.startswith(".") for part in parts):
        return None
    if PurePosixPath(path).suffix.lower() not in IMAGE_MEDIA_TYPES:
        return None
    candidate = corpus_root.joinpath(*parts)
    if not (candidate.parent / WRAPPED_DOCUMENT_FILENAME).is_file():
        return None
    return candidate if candidate.is_file() else None


def media_type_of(figure: Path) -> str:
    """The media type a held figure is served as."""
    return IMAGE_MEDIA_TYPES[figure.suffix.lower()]


def figure_addresses(corpus_root: Path, document_path: str) -> FigureAddress | None:
    """Where the figures of the document at `document_path` are served, as
    a function of the name its markdown refers to one by.

    None for a document that is a single file: only a directory of its own
    holds a figure. The function answers None for a name with no figure.
    A name that is a path needs no rule here: `held_figure` answers only a
    file beside a `content.md`, and refuses a path that climbs.
    """
    document = PurePosixPath(document_path)
    if document.name != WRAPPED_DOCUMENT_FILENAME:
        return None
    directory = document.parent.as_posix()

    def address(name: str) -> str | None:
        path = f"{directory}/{name}"
        if held_figure(corpus_root, path) is None:
            return None
        return f"{FIGURE_ROUTE}/{quote(path)}"

    return address


__all__ = ["FIGURE_ROUTE", "figure_addresses", "held_figure", "media_type_of"]
