"""A store of annotations as the tag tests read it: by tag, each target a
document, the chunk it was last placed in, and its selected words.

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
    read_annotations,
    written,
)

ANNOTATIONS: Final = ANNOTATIONS_FILENAME


@dataclass(frozen=True, slots=True)
class Target:
    """What a tag is on: the document, and for a selection the chunk it
    was last placed in and its words."""

    document: str
    chunk: int | None = None
    quote: str | None = None


def target_of(annotation: Annotation) -> Target:
    selector = annotation.selector
    if selector is None:
        return Target(annotation.document)
    return Target(annotation.document, selector.chunk, selector.exact)


def tagged(root: Path) -> dict[str, tuple[Target, ...]]:
    """The store in `root` (the corpus root or a `.context/`), by tag."""
    store = read_annotations(root / ANNOTATIONS)
    by_tag: dict[str, list[Target]] = {}
    for annotation in store.annotations:
        for name in annotation.tags:
            by_tag.setdefault(name, []).append(target_of(annotation))
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
