"""Turning engine values into what a template places.

The interface's half of `render/`. It calls the shared renderers -
`render/hits.py` for a hit, `render/html.py` for a document - and
arranges what comes back into values a template can lay out without
deciding anything itself.

**A template does no formatting.** Everything a person reads is
composed here or in `render/`, so that a change of layout cannot
change a word and a change of wording cannot need a template edit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.gui import words
from kennis.holdings import Holding
from kennis.render.hits import (
    Hit,
    ScoreStyle,
    best_lexical,
    rendered_hit,
    score_style_for,
)
from kennis.render.html import to_html

# Bands rather than raw fused scores, as the other two front ends use:
# a fused score is a function of rank and says nothing an ordered list
# does not already say.
_STYLE: ScoreStyle = "human"


@dataclass(frozen=True, slots=True)
class ShownHit:
    """One hit, in the pieces a page arranges.

    The three text fields come from `render/hits.py::rendered_hit`, so
    what is read here is what `kennis search` prints and what an agent
    is handed. The two extra fields are coordinates, not words: a page
    needs them to build a link, and a link is not something `render/`
    should be composing.
    """

    headline: str
    detail: str
    body: str | None
    collection: str
    document_id: str


def shown_hits(hits: list[Hit]) -> list[ShownHit]:
    """Every hit, rendered once, in rank order."""
    if not hits:
        return []
    style, _ = score_style_for(hits, _STYLE)
    best = best_lexical(hits)
    shown: list[ShownHit] = []
    for rank, hit in enumerate(hits, start=1):
        rendered = rendered_hit(hit, rank=rank, style=style, best=best, snippet="short")
        shown.append(
            ShownHit(
                headline=rendered.headline,
                detail=rendered.detail,
                body=rendered.body,
                collection=hit.collection,
                document_id=hit.result.chunk.document_id,
            )
        )
    return shown


@dataclass(frozen=True, slots=True)
class ShownDocument:
    """One document, ready to place."""

    title: str
    document_id: str
    collection: str
    path: str
    body_html: str
    # True when the body referred to an image that was not fetched, so
    # a page can offer to load them. Offered only when there is
    # something to load, because a control that does nothing is worse
    # than no control.
    has_blocked_images: bool


def shown_document(
    corpus_root: Path, collection: str, document_id: str, *, load_remote_images: bool
) -> ShownDocument:
    """Read one document and render it.

    Raises `DocumentNotFound` or `DocumentInvalid`, which the interface
    turns into a page rather than a traceback.
    """
    held = Collection(root=corpus_root, name=collection)
    document = held.resolve(document_id)
    return ShownDocument(
        title=document.frontmatter.title,
        document_id=document.id,
        collection=collection,
        path=relative_to_corpus(document.md_path, corpus_root),
        body_html=to_html(document.body, load_remote_images=load_remote_images),
        has_blocked_images=_refers_remotely(document.body),
    )


def _refers_remotely(markdown: str) -> bool:
    """Whether the body refers to an image kennis would have to fetch.

    Crude on purpose - a substring, not a parse. Being wrong here
    offers a control that loads nothing, or withholds one the reader
    could have used; neither justifies parsing the document twice.
    """
    return "](http://" in markdown or "](https://" in markdown


__all__ = [
    "ShownDocument",
    "ShownEntry",
    "ShownHit",
    "ShownRow",
    "shown_document",
    "shown_groups",
    "shown_hits",
    "shown_rows",
]


@dataclass(frozen=True, slots=True)
class ShownRow:
    """One collection, as a table row."""

    collection: str
    count: str
    index: str
    is_current: bool


@dataclass(frozen=True, slots=True)
class ShownEntry:
    """One document in a listing: what to show and what to link to."""

    title: str
    document_id: str


def shown_rows(held: Sequence[Holding]) -> list[ShownRow]:
    """Every collection, phrased for a table."""
    return [
        ShownRow(
            collection=holding.collection,
            count=words.describe_count(holding),
            index=words.describe_holding(holding),
            is_current=holding.is_current,
        )
        for holding in held
    ]


def shown_groups(
    corpus_root: Path, collection: str
) -> tuple[list[tuple[str, list[ShownEntry]]], int]:
    """A collection's documents by group, and how many could not be read.

    Grouped by the directory a document sits in, which is what the
    corpus layout means by a group - `corpus tree` shows the same
    shape. The ungrouped ones come first under an empty name, because
    a collection with no groups should not lead with a heading.
    """
    contents = Collection(root=corpus_root, name=collection).contents()
    grouped: dict[str, list[ShownEntry]] = {}
    for document in sorted(contents.documents, key=_sort_key):
        grouped.setdefault(_group_of(corpus_root, collection, document), []).append(
            ShownEntry(title=document.frontmatter.title, document_id=document.id)
        )
    ordered = sorted(grouped.items(), key=lambda pair: (pair[0] != "", pair[0]))
    return ordered, len(contents.unreadable)


def _sort_key(document: Document) -> str:
    return document.frontmatter.title.casefold()


def _group_of(corpus_root: Path, collection: str, document: Document) -> str:
    """The directory below the collection that this document sits in.

    The wrapper is the anchor for a wrapped document, because its own
    directory *is* the document rather than a group - the same rule
    the index loader follows.
    """
    anchor = document.wrapper_dir or document.md_path
    relative = anchor.relative_to(corpus_root / collection)
    return relative.parent.as_posix() if relative.parent.name else ""
