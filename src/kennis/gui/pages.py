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

from dataclasses import dataclass
from pathlib import Path

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import relative_to_corpus
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


__all__ = ["ShownDocument", "ShownHit", "shown_document", "shown_hits"]
