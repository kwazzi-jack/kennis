"""A store of annotations as the tag tests read it: by tag, each target a
document, the first chunk the index links it to, and its selected words.

The tests that tag through a front end assert what was stored; this view
keeps their assertions about tags rather than about the file's layout,
which `tests/test_annotations.py` holds on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.annotations import (
    ANNOTATIONS_FILENAME,
    Annotation,
    AnnotationStore,
    links,
    read_annotations,
    written,
)
from kennis.engine.rag.models import Chunk

ANNOTATIONS: Final = ANNOTATIONS_FILENAME


@dataclass(frozen=True, slots=True)
class Target:
    """What a tag is on: the document, and for a selection the first chunk
    the index links it to (None when none does) and its words."""

    document: str
    chunk: int | None = None
    quote: str | None = None


def indexed_chunks(root: Path) -> list[Chunk]:
    """Every chunk of the index beside `root`: a `.context/` bundle's, or
    each corpus collection's that has one."""
    from kennis.engine.context.bundle import index_root_for
    from kennis.engine.corpus.layout import index_root
    from kennis.engine.corpus.schema import COLLECTION_NAMES
    from kennis.engine.errors import KennisError
    from kennis.engine.rag.index import load_chunks

    if root.name == ".context":
        places = [(index_root_for(root), "context")]
    else:
        places = [(index_root(root), name) for name in COLLECTION_NAMES]
    chunks: list[Chunk] = []
    for index, collection in places:
        try:
            chunks.extend(load_chunks(index, collection))
        except KennisError:
            continue
    return chunks


def tagged(root: Path) -> dict[str, tuple[Target, ...]]:
    """The store in `root` (the corpus root or a `.context/`), by tag."""
    store = read_annotations(root / ANNOTATIONS)
    chunks = indexed_chunks(root)
    linked = links(store, chunks)
    numbers = {chunk.id: chunk.chunk_index for chunk in chunks}
    by_tag: dict[str, list[Target]] = {}
    for annotation in store.annotations:
        selector = annotation.selector
        if selector is None:
            target = Target(annotation.document)
        else:
            carried = [
                numbers[each] for each in linked.by_annotation.get(annotation.id, ())
            ]
            target = Target(
                annotation.document, min(carried) if carried else None, selector.exact
            )
        for name in annotation.tags:
            by_tag.setdefault(name, []).append(target)
    return {name: tuple(targets) for name, targets in sorted(by_tag.items())}


def colours_in(root: Path) -> dict[str, str]:
    return read_annotations(root / ANNOTATIONS).colours


def write_store(root: Path, store: AnnotationStore) -> None:
    (root / ANNOTATIONS).write_text(written(store), encoding="utf-8")


def whole_document(
    document: str, tags: tuple[str, ...], identifier: str = "0000000a"
) -> Annotation:
    return Annotation(
        id=identifier,
        document=document,
        selector=None,
        tags=tuple(sorted(tags)),
        comment=None,
        created="2026-11-16T10:00:00+00:00",
    )
