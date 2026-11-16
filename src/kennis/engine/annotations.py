"""Annotations: a selection of a document's text, with tags and a comment
(#50, sketch 2026-11-16-annotations).

**One record** (Brian, 2026-11-16). An annotation is a selection - or the
whole document - carrying zero or more tags and an optional comment. A tag
on a search hit is an annotation over that chunk's span. Tag names and
colours are `engine/tags.py`'s; this module keeps the records.

**A selection is found again by its words** (the W3C Web Annotation text
quote selector): the whole selected text, a few dozen characters either
side, and its offsets into `Document.body` as a hint - the coordinates
`Chunk.char_start` uses. Offsets alone go out of date with an edit, a
reconversion or a new chunker; the words decide. Found, the selection is
placed there; found nowhere, it is detached - never moved to a neighbour
nor widened to the document, because an annotation that moved in silence
is a citation of the wrong text.

**One rule, the caller's text.** `located` works on whatever text the
caller has: the window the body it renders, search and the listing a
document's indexed text, which `indexed_text` rebuilds from its chunks
because a chunk's text is exactly `body[char_start:char_end]`.

**Where.** A store is one file, `annotations.json`: the corpus's at its
root, committed by kennis, and a project's in `.context/`, left for the
person to commit. Written with sorted keys and `ensure_ascii`, so it stays
ASCII and an accent survives as an escape. `tags.yml`, the store before
this, is not read (Brian, 2026-11-16: start fresh).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kennis.engine.errors import (
    AnnotationsUnreadable,
    TagColourRefused,
    TagNameRefused,
)
from kennis.engine.rag.models import Chunk, ChunkPredicate
from kennis.engine.tags import tag_colour, tag_name

ANNOTATIONS_FILENAME: Final = "annotations.json"

# Characters kept either side of a selection to tell repeated words apart.
CONTEXT_CHARACTERS: Final = 32

_FORMAT: Final = 1
_ID_LENGTH: Final = 8
_ID: Final = re.compile(r"[0-9a-f]{8}")


@dataclass(frozen=True, slots=True)
class Span:
    """A range of a text, `end` exclusive."""

    start: int
    end: int

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end


@dataclass(frozen=True, slots=True)
class Selector:
    """A selection, by its words.

    `exact` is the whole selected text and `prefix` and `suffix` what was
    either side of it; `start` and `end` are where it was last found, a
    hint. No chunk is kept: which chunks carry a selection is derived
    (`links`), because a chunk is the index's and not the reader's.
    """

    exact: str
    prefix: str
    suffix: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Annotation:
    """A selection of `document`, or the whole of it when `selector` is
    None, with its tags in order of name and an optional comment."""

    id: str
    document: str
    selector: Selector | None
    tags: tuple[str, ...]
    comment: str | None
    created: str

    def is_empty(self) -> bool:
        return not self.tags and not self.comment


@dataclass(frozen=True, slots=True)
class AnnotationStore:
    """One `annotations.json`: its annotations, in the order they were
    made, and the colours chosen for some tags."""

    annotations: tuple[Annotation, ...] = ()
    colours: dict[str, str] = field(default_factory=dict)

    def tag_names(self) -> set[str]:
        return {name for annotation in self.annotations for name in annotation.tags}


@dataclass(frozen=True, slots=True)
class Placed:
    """Found: at `span` of the text; None for the whole document."""

    span: Span | None


@dataclass(frozen=True, slots=True)
class Detached:
    """The selection's words are nowhere in its document."""


@dataclass(frozen=True, slots=True)
class Unchecked:
    """The index does not hold the document, so it cannot say."""


type Placement = Placed | Detached | Unchecked


# ---------------------------------------------------------------------------
# The file


class _SelectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exact: str = Field(min_length=1)
    prefix: str
    suffix: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class _AnnotationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document: str = Field(min_length=1)
    selector: _SelectorRecord | None = None
    tags: list[str] = Field(default_factory=list)
    comment: str | None = None
    created: str

    @field_validator("id")
    @classmethod
    def _an_id(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("an id is eight lowercase hexadecimal characters")
        return value

    @field_validator("tags")
    @classmethod
    def _folded_names(cls, value: list[str]) -> list[str]:
        for name in value:
            try:
                folded = tag_name(name)
            except TagNameRefused as refused:
                raise ValueError(str(refused)) from refused
            if folded != name:
                raise ValueError(f"the tag '{name}' is written as '{folded}'")
        if len(set(value)) != len(value):
            raise ValueError("a tag is named twice")
        return value


class _StoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal[1]
    annotations: list[_AnnotationRecord] = Field(default_factory=list)
    colours: dict[str, str] = Field(default_factory=dict)


def read_annotations(path: Path) -> AnnotationStore:
    """The annotations `path` holds and the colours chosen; empty when it
    does not exist. A file that does not have the shape kennis writes is
    refused with what is wrong, and never rewritten."""
    if not path.is_file():
        return AnnotationStore()
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return AnnotationStore()
    try:
        record = _StoreRecord.model_validate(json.loads(text))
    except json.JSONDecodeError as error:
        raise _unreadable(path, f"it is not JSON: {error}") from error
    except ValidationError as error:
        problem = error.errors()[0]
        where = ".".join(str(part) for part in problem["loc"]) or "the file"
        raise _unreadable(path, f"{where}: {problem['msg']}") from error
    seen: set[str] = set()
    annotations: list[Annotation] = []
    for each in record.annotations:
        if each.id in seen:
            raise _unreadable(path, f"the id {each.id} is used twice")
        seen.add(each.id)
        annotations.append(_annotation(each))
    colours: dict[str, str] = {}
    for name, colour in record.colours.items():
        try:
            colours[tag_name(name)] = tag_colour(colour)
        except (TagNameRefused, TagColourRefused) as refused:
            raise _unreadable(path, f"colours.{name}: {refused}") from refused
    held = {name for annotation in annotations for name in annotation.tags}
    return AnnotationStore(
        tuple(annotations),
        {name: colour for name, colour in colours.items() if name in held},
    )


def _annotation(record: _AnnotationRecord) -> Annotation:
    selector = record.selector
    return Annotation(
        id=record.id,
        document=record.document,
        selector=None
        if selector is None
        else Selector(
            selector.exact,
            selector.prefix,
            selector.suffix,
            selector.start,
            selector.end,
        ),
        tags=tuple(sorted(record.tags)),
        comment=record.comment or None,
        created=record.created,
    )


def _unreadable(path: Path, why: str) -> AnnotationsUnreadable:
    return AnnotationsUnreadable(
        f"{path} cannot be read as annotations, because {why}; kennis leaves it "
        "as it is until it is mended by hand"
    )


def written(store: AnnotationStore) -> str:
    """`store` as the file's text, or "" when it holds nothing.

    An annotation with no tag and no comment is not kept, nor the colour
    of a tag nothing carries.
    """
    kept = [annotation for annotation in store.annotations if not annotation.is_empty()]
    if not kept:
        return ""
    held = {name for annotation in kept for name in annotation.tags}
    document = {
        "format": _FORMAT,
        "annotations": [_record_of(annotation) for annotation in kept],
        "colours": {
            name: colour for name, colour in store.colours.items() if name in held
        },
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _record_of(annotation: Annotation) -> dict[str, object]:
    record: dict[str, object] = {
        "id": annotation.id,
        "document": annotation.document,
        "tags": list(annotation.tags),
        "created": annotation.created,
    }
    if annotation.comment:
        record["comment"] = annotation.comment
    selector = annotation.selector
    if selector is not None:
        record["selector"] = {
            "exact": selector.exact,
            "prefix": selector.prefix,
            "suffix": selector.suffix,
            "start": selector.start,
            "end": selector.end,
        }
    return record


# ---------------------------------------------------------------------------
# Making and changing


def selector_of(text: str, start: int, end: int) -> Selector:
    """The selector for `text[start:end]`, which must hold a word."""
    if not 0 <= start < end <= len(text) or not text[start:end].strip():
        raise ValueError(f"{start}..{end} selects no words of the text")
    return Selector(
        exact=text[start:end],
        prefix=text[max(0, start - CONTEXT_CHARACTERS) : start],
        suffix=text[end : end + CONTEXT_CHARACTERS],
        start=start,
        end=end,
    )


def new_id(taken: Iterable[str]) -> str:
    """An id no annotation in `taken` has."""
    used = set(taken)
    while True:
        candidate = secrets.token_hex(_ID_LENGTH // 2)
        if candidate not in used:
            return candidate


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def same_selection(one: Selector | None, other: Selector | None) -> bool:
    """Whether two selectors name one selection: both the whole document,
    or the same words at the same place."""
    if one is None or other is None:
        return one is other
    return (one.exact, one.start) == (other.exact, other.start)


def with_tags(
    store: AnnotationStore,
    document: str,
    selector: Selector | None,
    names: Sequence[str],
) -> tuple[AnnotationStore, tuple[str, ...]]:
    """`store` with each of `names` on the selection, and which were added.

    The annotation already on that selection takes them; otherwise one is
    made carrying all of them.
    """
    annotations = list(store.annotations)
    for position, annotation in enumerate(annotations):
        if annotation.document == document and same_selection(
            annotation.selector, selector
        ):
            added = tuple(name for name in names if name not in annotation.tags)
            annotations[position] = replace(
                annotation, tags=tuple(sorted({*annotation.tags, *added}))
            )
            return replace(store, annotations=tuple(annotations)), added
    added = tuple(dict.fromkeys(names))
    if not added:
        return store, ()
    annotations.append(
        Annotation(
            id=new_id(each.id for each in annotations),
            document=document,
            selector=selector,
            tags=tuple(sorted(added)),
            comment=None,
            created=now(),
        )
    )
    return replace(store, annotations=tuple(annotations)), added


def without_tags(
    store: AnnotationStore,
    chosen: Sequence[str],
    names: Sequence[str],
) -> tuple[AnnotationStore, tuple[str, ...]]:
    """`store` with `names` taken from the annotations whose ids are
    `chosen`, and which names any of them carried. An annotation left with
    no tag and no comment is dropped."""
    removed: list[str] = []
    kept: list[Annotation] = []
    for annotation in store.annotations:
        if annotation.id in chosen:
            gone = [name for name in names if name in annotation.tags]
            removed.extend(gone)
            annotation = replace(
                annotation,
                tags=tuple(name for name in annotation.tags if name not in names),
            )
            if annotation.is_empty():
                continue
        kept.append(annotation)
    return (
        replace(store, annotations=tuple(kept)),
        tuple(dict.fromkeys(name for name in names if name in removed)),
    )


# ---------------------------------------------------------------------------
# Finding a selection again


def located(selector: Selector, text: str) -> Span | None:
    """Where `selector`'s words are in `text`, or None.

    At the hinted offsets when they still hold the words; otherwise the
    occurrence - whitespace runs matching any whitespace, since a
    reconversion moves line breaks and not words - whose surroundings agree
    longest with the prefix and suffix, then the nearest the hint.
    """
    start, end = selector.start, selector.end
    if 0 <= start <= end <= len(text) and text[start:end] == selector.exact:
        return Span(start, end)
    pattern = _words_pattern(selector.exact)
    found = [Span(match.start(), match.end()) for match in pattern.finditer(text)]
    if not found:
        return None
    return max(
        found,
        key=lambda span: (_agreement(text, span, selector), -abs(span.start - start)),
    )


def _words_pattern(exact: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(word) for word in exact.split()))


def _agreement(text: str, span: Span, selector: Selector) -> int:
    """How many characters either side of `span` agree with the selector's
    prefix and suffix, whitespace collapsed."""
    reach = 2 * CONTEXT_CHARACTERS
    before = _collapsed(text[max(0, span.start - reach) : span.start])
    after = _collapsed(text[span.end : span.end + reach])
    prefix = _collapsed(selector.prefix)
    suffix = _collapsed(selector.suffix)
    agreed = 0
    while (
        agreed < min(len(before), len(prefix))
        and before[-1 - agreed] == prefix[-1 - agreed]
    ):
        agreed += 1
    following = 0
    while (
        following < min(len(after), len(suffix))
        and after[following] == suffix[following]
    ):
        following += 1
    return agreed + following


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def indexed_text(chunks: Sequence[Chunk]) -> str:
    """One document's text as its index holds it: each chunk at its
    offsets, and the gaps - which the chunker leaves only where the text
    is blank - as spaces."""
    pieces: list[str] = []
    length = 0
    for chunk in sorted(chunks, key=lambda each: each.char_start):
        if chunk.char_start > length:
            pieces.append(" " * (chunk.char_start - length))
            length = chunk.char_start
        if chunk.char_end > length:
            pieces.append(chunk.text[length - chunk.char_start :])
            length = chunk.char_end
    return "".join(pieces)


def own_ranges(chunks: Sequence[Chunk]) -> dict[str, Span]:
    """Each chunk's own text, by chunk id: from its start to where the next
    chunk of its document starts, or its own end if sooner.

    A long block is cut into overlapping windows, so a chunk's start is
    inside the one before. Own ranges do not overlap: each character of a
    document is in one chunk's own text, which is what lets a selection be
    linked to the chunks it is in without also being linked to a
    neighbour that merely shares some of its characters. The chunks
    themselves, and what search scores, are untouched.
    """
    ranges: dict[str, Span] = {}
    for own in by_document(chunks).values():
        ordered = sorted(own, key=lambda chunk: chunk.char_start)
        for position, chunk in enumerate(ordered):
            following = ordered[position + 1 :]
            stop = chunk.char_end
            if following:
                stop = min(stop, following[0].char_start)
            ranges[chunk.id] = Span(chunk.char_start, stop)
    return ranges


def own_end(chunks: Sequence[Chunk], chunk: Chunk) -> int:
    """Where `chunk`'s own text ends among `chunks`; see `own_ranges`."""
    return own_ranges(
        [each for each in chunks if each.document_id == chunk.document_id]
    )[chunk.id].end


@dataclass(frozen=True, slots=True)
class AnnotationLinks:
    """Which chunks of one index carry which annotations: the rows
    (annotation id, chunk id), looked up from either side."""

    by_annotation: dict[str, tuple[str, ...]] = field(default_factory=dict)
    by_chunk: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def of(cls, rows: Mapping[str, Sequence[str]]) -> AnnotationLinks:
        by_chunk: dict[str, list[str]] = {}
        for annotation, chunk_ids in rows.items():
            for chunk_id in chunk_ids:
                by_chunk.setdefault(chunk_id, []).append(annotation)
        return cls(
            {annotation: tuple(ids) for annotation, ids in rows.items() if ids},
            {chunk_id: tuple(ids) for chunk_id, ids in by_chunk.items()},
        )


def links(store: AnnotationStore, chunks: Sequence[Chunk]) -> AnnotationLinks:
    """The rows linking `store`'s annotations to `chunks`.

    A whole-document annotation is linked to every chunk of its document.
    A selection, found by `located` in its document's indexed text, is
    linked to every chunk whose own text (`own_ranges`) it intersects - so
    one selection across two chunks is on both, and a tag on one window
    is not on the window it overlaps. A detached selection, or one whose
    document this index does not hold, is linked to none.
    """
    grouped = by_document(chunks)
    own = own_ranges(chunks)
    texts: dict[str, str] = {}
    rows: dict[str, list[str]] = {}
    for annotation in store.annotations:
        held = sorted(
            grouped.get(annotation.document, []), key=lambda chunk: chunk.char_start
        )
        if not held:
            continue
        if annotation.selector is None:
            rows[annotation.id] = [chunk.id for chunk in held]
            continue
        if annotation.document not in texts:
            texts[annotation.document] = indexed_text(held)
        span = located(annotation.selector, texts[annotation.document])
        if span is None:
            continue
        rows[annotation.id] = [
            chunk.id
            for chunk in held
            if span.overlaps(own[chunk.id].start, own[chunk.id].end)
        ]
    return AnnotationLinks.of(rows)


_LINKS_FILENAME: Final = "annotation-links.json"


def store_digest(path: Path) -> str:
    """The sha256 of a store's text, or of nothing when there is none."""
    content = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(content).hexdigest()


def links_for(index_root: Path, collection: str, store_path: Path) -> AnnotationLinks:
    """The links between the store at `store_path` and the published index
    of `collection`, read from beside that index build or computed.

    The cache lives in the build's own directory, which git ignores and a
    new build replaces, so it cannot outlive its index; it records the
    digest of the store it was computed from, and a different one means it
    is computed again. Two processes computing at once write the same
    text, each by replacement. Raises what `load_chunks` raises when there
    is no index.
    """
    from kennis.engine.atomic import replace_file
    from kennis.engine.rag.index import load_chunks, published_directory

    cache = published_directory(index_root, collection) / _LINKS_FILENAME
    digest = store_digest(store_path)
    cached = _cached_links(cache, digest)
    if cached is not None:
        return cached
    computed = links(read_annotations(store_path), load_chunks(index_root, collection))
    replace_file(
        cache,
        json.dumps(
            {"store": digest, "links": computed.by_annotation},
            sort_keys=True,
            ensure_ascii=True,
        ),
    )
    return computed


def _cached_links(cache: Path, digest: str) -> AnnotationLinks | None:
    """The cache's links when it was computed from this store; None when it
    is absent, from another store, or not what kennis writes."""
    try:
        document = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("store") != digest:
        return None
    rows = document.get("links")
    if not isinstance(rows, dict):
        return None
    checked: dict[str, list[str]] = {}
    for annotation, chunk_ids in rows.items():
        if not isinstance(chunk_ids, list) or not all(
            isinstance(each, str) for each in chunk_ids
        ):
            return None
        checked[str(annotation)] = chunk_ids
    return AnnotationLinks.of(checked)


def placed(annotation: Annotation, chunks: Sequence[Chunk]) -> Placement:
    """Where `annotation` is among its document's `chunks` in one index."""
    own = [chunk for chunk in chunks if chunk.document_id == annotation.document]
    if not own:
        return Unchecked()
    if annotation.selector is None:
        return Placed(None)
    span = located(annotation.selector, indexed_text(own))
    return Detached() if span is None else Placed(span)


def by_document(chunks: Iterable[Chunk]) -> dict[str, list[Chunk]]:
    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)
    return grouped


def rehinted(store: AnnotationStore, chunks: Sequence[Chunk]) -> AnnotationStore:
    """`store` with each selection's hint, and the words either side of it,
    set to where `chunks` place it now (#626).

    The nearest occurrence of repeated words is taken by the hint, so a
    hint rewritten after each edit follows its selection. A detached or
    unchecked selection keeps its hint, there being nothing better to say.
    """
    grouped = by_document(chunks)
    texts: dict[str, str] = {}
    changed: list[Annotation] = []
    for annotation in store.annotations:
        selector = annotation.selector
        own = grouped.get(annotation.document, [])
        if selector is None or not own:
            changed.append(annotation)
            continue
        if annotation.document not in texts:
            texts[annotation.document] = indexed_text(own)
        text = texts[annotation.document]
        span = located(selector, text)
        if span is None:
            changed.append(annotation)
            continue
        changed.append(
            replace(annotation, selector=selector_of(text, span.start, span.end))
        )
    return replace(store, annotations=tuple(changed))


def tags_on(
    store: AnnotationStore, linked: AnnotationLinks, chunk: Chunk
) -> list[tuple[str, bool]]:
    """The tags `chunk` carries by `linked`, in order of name, each with
    whether it is on the whole document."""
    carried = set(linked.by_chunk.get(chunk.id, ()))
    whole: set[str] = set()
    passage: set[str] = set()
    for annotation in store.annotations:
        if annotation.id in carried:
            (whole if annotation.selector is None else passage).update(annotation.tags)
    return [(name, name in whole) for name in sorted(whole | passage)]


def admitting(
    store: AnnotationStore, names: Sequence[str], chunks: Sequence[Chunk]
) -> ChunkPredicate:
    """Whether a chunk of this index carries every one of `names`, by the
    links between `store` and `chunks`. A name the store does not hold
    admits nothing, so several names intersect."""
    linked = links(store, chunks)
    tags_of = {annotation.id: annotation.tags for annotation in store.annotations}
    wanted = set(names)

    def admits(chunk: Chunk) -> bool:
        carried = {
            name
            for annotation in linked.by_chunk.get(chunk.id, ())
            for name in tags_of.get(annotation, ())
        }
        return wanted <= carried

    return admits


def annotations_of(store: AnnotationStore, document: str) -> list[Annotation]:
    return [each for each in store.annotations if each.document == document]


def colours_kept(store: AnnotationStore, colours: Mapping[str, str]) -> AnnotationStore:
    return replace(store, colours=dict(colours))


__all__ = [
    "ANNOTATIONS_FILENAME",
    "CONTEXT_CHARACTERS",
    "Annotation",
    "AnnotationLinks",
    "AnnotationStore",
    "Detached",
    "Placed",
    "Placement",
    "Selector",
    "Span",
    "Unchecked",
    "admitting",
    "annotations_of",
    "by_document",
    "colours_kept",
    "indexed_text",
    "links",
    "links_for",
    "located",
    "new_id",
    "now",
    "own_end",
    "own_ranges",
    "placed",
    "read_annotations",
    "rehinted",
    "same_selection",
    "selector_of",
    "store_digest",
    "tags_on",
    "with_tags",
    "without_tags",
    "written",
]
