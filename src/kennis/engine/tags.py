"""Tags on a document or a passage, and finding a passage again (#625).

A tag is a flat, free-form name folded to lowercase (Brian, 2026-11-06):
no whitespace or comma, because those separate tags as they are typed, and
`/` an ordinary character with no hierarchy, as in the traditional systems
(Delicious, Pinboard, Zotero). A tagged passage is what the window calls a
bookmark; there is no second concept.

**Where.** A store is one file, `tags.yml`, keyed by tag so a person reading
it sees what they gathered under each: the corpus's at its root, committed
by kennis, and a project's in `.context/`, left for the person to commit.
Never in frontmatter: a pack's notes and docs pages are read-only, and a
tag written into a pack's copy in `.context/` would read as an edit (#624).
This module reads and writes the text; the caller places it.

**A target** is a document - a corpus identifier, or a path in a bundle,
which always ends `.md` (the bundle indexes nothing else) and is written
`path:` - and, for a passage, the chunk it was tagged at and a quotation of
its opening. A chunk number is a hint and nothing more: an edit, a docs
refresh or a new chunker renumbers chunks (version 3 renumbered every one).
The words decide. Found in the hinted chunk or another of the document's,
the passage is placed there; found in none, it is detached - never moved to
a nearby passage nor widened to the document, because a bookmark that moved
in silence is a citation of the wrong text. Matching reads the index's
chunk texts rather than the body, so a stale index cannot put offsets out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from kennis.engine.errors import TagNameRefused, TagsUnreadable
from kennis.engine.frontmatter import yaml_text
from kennis.engine.rag.models import Chunk, ChunkPredicate

TAGS_FILENAME: Final = "tags.yml"

# Long enough to be one passage's own words, short enough that a chunker
# drawing its boundaries elsewhere still holds them in one chunk.
_QUOTE_LENGTH: Final = 80
_DOCUMENT_KEY: Final = "document"
_PATH_KEY: Final = "path"
_CHUNK_KEY: Final = "chunk"
_QUOTE_KEY: Final = "quote"
_BUNDLE_SUFFIX: Final = ".md"


@dataclass(frozen=True, slots=True)
class Anchor:
    """What a tag names: a document, and the passage if one.

    Two anchors are one target when their document and chunk agree; the
    quotation is how the passage is found again, not part of its name.
    """

    document: str
    chunk: int | None = None
    quote: str | None = None

    def names_the_same(self, other: Anchor) -> bool:
        return self.document == other.document and self.chunk == other.chunk


type Tags = dict[str, tuple[Anchor, ...]]


@dataclass(frozen=True, slots=True)
class Placed:
    """Found: at `chunk`, or the whole document when None."""

    chunk: int | None


@dataclass(frozen=True, slots=True)
class Detached:
    """The passage's words are in no chunk of its document."""


@dataclass(frozen=True, slots=True)
class Unchecked:
    """The index does not hold the document, so it cannot say."""


type Placement = Placed | Detached | Unchecked


# ---------------------------------------------------------------------------
# Names


def tag_name(text: str) -> str:
    """`text` as a tag, folded, or `TagNameRefused`."""
    name = text.strip().lower()
    if not name or any(
        character.isspace() or character == "," or ord(character) < 32
        for character in name
    ):
        raise TagNameRefused(
            f"'{text}' is not a tag name: {TagNameRefused.default_message}"
        )
    return name


def split_tag_names(text: str) -> tuple[str, ...]:
    """Comma-separated names as typed, each folded, each kept once."""
    return tuple(dict.fromkeys(tag_name(part) for part in text.split(",")))


# ---------------------------------------------------------------------------
# The file


def read_tags(path: Path) -> Tags:
    """The tags `path` holds; none when it does not exist."""
    from kennis.engine.pack.schema import read_yaml

    if not path.is_file():
        return {}
    try:
        document = read_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise _unreadable(path, f"it is not YAML: {error}") from error
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise _unreadable(path, "it is not a mapping of tags to their targets")
    held: Tags = {}
    for key, targets in document.items():
        if not isinstance(key, str):
            raise _unreadable(path, f"the tag {key!r} is not a name")
        try:
            name = tag_name(key)
        except TagNameRefused as refused:
            raise _unreadable(path, str(refused)) from refused
        if name != key:
            raise _unreadable(path, f"the tag '{key}' is written as '{name}'")
        if targets is None:
            continue
        if not isinstance(targets, list):
            raise _unreadable(path, f"the tag '{key}' holds no list of targets")
        held[name] = tuple(_anchor(path, key, target) for target in targets)
    return {name: anchors for name, anchors in held.items() if anchors}


def _anchor(path: Path, name: str, target: object) -> Anchor:
    if not isinstance(target, dict):
        raise _unreadable(path, f"a target of '{name}' is not a mapping")
    unknown = set(target) - {_DOCUMENT_KEY, _PATH_KEY, _CHUNK_KEY, _QUOTE_KEY}
    if unknown:
        raise _unreadable(
            path, f"a target of '{name}' has {', '.join(sorted(map(str, unknown)))}"
        )
    named = [target[key] for key in (_DOCUMENT_KEY, _PATH_KEY) if key in target]
    if len(named) != 1 or not isinstance(named[0], str) or not named[0]:
        raise _unreadable(
            path, f"a target of '{name}' names neither one document nor one path"
        )
    chunk = target.get(_CHUNK_KEY)
    if chunk is not None and (
        isinstance(chunk, bool) or not isinstance(chunk, int) or chunk < 0
    ):
        raise _unreadable(path, f"a target of '{name}' has the chunk {chunk!r}")
    quote = target.get(_QUOTE_KEY)
    if quote is not None and not isinstance(quote, str):
        raise _unreadable(path, f"a target of '{name}' has a quote that is not text")
    return Anchor(named[0], chunk, quote)


def _unreadable(path: Path, why: str) -> TagsUnreadable:
    return TagsUnreadable(
        f"{path} cannot be read as tags, because {why}; kennis leaves it as it "
        "is until it is mended by hand"
    )


def written(held: Mapping[str, Sequence[Anchor]]) -> str:
    """`held` as the file's text: tags in order of name, targets in the
    order they were tagged. A tag with no targets is left out."""
    document = {
        name: [_target(anchor) for anchor in held[name]]
        for name in sorted(held)
        if held[name]
    }
    return yaml_text(document) if document else ""


def _target(anchor: Anchor) -> dict[str, str | int]:
    key = _PATH_KEY if anchor.document.endswith(_BUNDLE_SUFFIX) else _DOCUMENT_KEY
    target: dict[str, str | int] = {key: anchor.document}
    if anchor.chunk is not None:
        target[_CHUNK_KEY] = anchor.chunk
    if anchor.quote is not None:
        target[_QUOTE_KEY] = anchor.quote
    return target


def with_tags(
    held: Mapping[str, Sequence[Anchor]], names: Sequence[str], anchor: Anchor
) -> Tags:
    """`held` with `anchor` under each of `names`; a target already there
    is left as it is."""
    changed: Tags = {name: tuple(anchors) for name, anchors in held.items()}
    for name in names:
        anchors = changed.get(name, ())
        if not any(each.names_the_same(anchor) for each in anchors):
            changed[name] = (*anchors, anchor)
    return changed


def without_tags(
    held: Mapping[str, Sequence[Anchor]], names: Sequence[str], anchor: Anchor
) -> Tags:
    """`held` with the target `anchor` names taken from under each of
    `names`; a tag left with none is dropped."""
    changed: Tags = {}
    for name, anchors in held.items():
        kept = (
            tuple(each for each in anchors if not each.names_the_same(anchor))
            if name in names
            else tuple(anchors)
        )
        if kept:
            changed[name] = kept
    return changed


# ---------------------------------------------------------------------------
# Finding a passage again


def quote_of(text: str) -> str:
    """The opening words of a chunk's text, whitespace collapsed, cut at a
    word near `_QUOTE_LENGTH` characters.

    Leading heading lines are passed over: a section's heading is not its
    passage's own words, and a chunker may draw a boundary between them.
    """
    lines = text.splitlines()
    while len(lines) > 1 and (
        not lines[0].strip() or lines[0].lstrip().startswith("#")
    ):
        lines = lines[1:]
    collapsed = _collapsed("\n".join(lines))
    if len(collapsed) <= _QUOTE_LENGTH:
        return collapsed
    cut = collapsed.rfind(" ", 0, _QUOTE_LENGTH + 1)
    return collapsed[: cut if cut > 0 else _QUOTE_LENGTH]


def placed(anchor: Anchor, chunks: Sequence[Chunk]) -> Placement:
    """Where `anchor` is among one index's `chunks`."""
    own = [chunk for chunk in chunks if chunk.document_id == anchor.document]
    if not own:
        return Unchecked()
    if anchor.chunk is None:
        return Placed(None)
    if anchor.quote is None:
        # Written by hand without words: the number is all there is.
        held = any(chunk.chunk_index == anchor.chunk for chunk in own)
        return Placed(anchor.chunk) if held else Detached()
    words = _collapsed(anchor.quote)
    # The hinted chunk first: it is where a passage almost always still is,
    # and the rest of a long docs page is hundreds of chunks to collapse.
    hinted = next((chunk for chunk in own if chunk.chunk_index == anchor.chunk), None)
    if hinted is not None and words in _collapsed(hinted.text):
        return Placed(anchor.chunk)
    holding = [chunk.chunk_index for chunk in own if words in _collapsed(chunk.text)]
    if not holding:
        return Detached()
    hint = anchor.chunk
    return Placed(min(holding, key=lambda number: (abs(number - hint), number)))


def admitting(
    held: Mapping[str, Sequence[Anchor]], names: Sequence[str], chunks: Sequence[Chunk]
) -> ChunkPredicate:
    """Whether a chunk of this index carries every one of `names`.

    A document tag admits each of its chunks; a passage tag the chunk it is
    placed at now among `chunks`, and nothing when it is detached. A name
    the store does not hold admits nothing, so several names intersect.
    """
    # Each passage is placed among its own document's chunks, grouped once:
    # placing it among all of them cost a pass over the index per tagged
    # passage, 100 ms for a hundred over ten thousand chunks.
    by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk.document_id, []).append(chunk)
    admitted: list[tuple[frozenset[str], frozenset[tuple[str, int]]]] = []
    for name in names:
        documents: set[str] = set()
        passages: set[tuple[str, int]] = set()
        for anchor in held.get(name, ()):
            if anchor.chunk is None:
                documents.add(anchor.document)
                continue
            where = placed(anchor, by_document.get(anchor.document, ()))
            if isinstance(where, Placed) and where.chunk is not None:
                passages.add((anchor.document, where.chunk))
        admitted.append((frozenset(documents), frozenset(passages)))

    def admits(chunk: Chunk) -> bool:
        return all(
            chunk.document_id in documents
            or (chunk.document_id, chunk.chunk_index) in passages
            for documents, passages in admitted
        )

    return admits


def _collapsed(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "TAGS_FILENAME",
    "Anchor",
    "Detached",
    "Placed",
    "Placement",
    "TagNameRefused",
    "Tags",
    "TagsUnreadable",
    "Unchecked",
    "admitting",
    "placed",
    "quote_of",
    "read_tags",
    "split_tag_names",
    "tag_name",
    "with_tags",
    "without_tags",
    "written",
]
