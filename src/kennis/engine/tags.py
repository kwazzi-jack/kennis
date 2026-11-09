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

import re
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml

from kennis.engine.errors import TagColourRefused, TagNameRefused, TagsUnreadable
from kennis.engine.frontmatter import yaml_text
from kennis.engine.rag.models import Chunk, ChunkPredicate

TAGS_FILENAME: Final = "tags.yml"

# A tag's colour is one of these names (#627), whose value each theme of
# the window draws from its own measured table, or a hex colour a person
# typed (#629).
TAG_COLOURS: Final = (
    "red",
    "orange",
    "yellow",
    "green",
    "teal",
    "blue",
    "purple",
    "pink",
)

# Long enough to be one passage's own words, short enough that a chunker
# drawing its boundaries elsewhere still holds them in one chunk.
_QUOTE_LENGTH: Final = 80
_DOCUMENT_KEY: Final = "document"
_PATH_KEY: Final = "path"
_CHUNK_KEY: Final = "chunk"
_QUOTE_KEY: Final = "quote"
_BUNDLE_SUFFIX: Final = ".md"
_COLOUR_KEY: Final = "colour"
_HEX: Final = re.compile(r"#[0-9a-f]{6}")
_SHORT_HEX: Final = re.compile(r"#[0-9a-f]{3}")
_TARGETS_KEY: Final = "targets"


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
class TagStore:
    """One `tags.yml`: its tags, and the colours chosen for some of them."""

    tags: Tags = field(default_factory=dict)
    colours: dict[str, str] = field(default_factory=dict)


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
    return read_store(path).tags


def read_store(path: Path) -> TagStore:
    """The tags `path` holds and their chosen colours; empty when it does
    not exist.

    A tag's value is its list of targets, or, when a colour was chosen, a
    mapping of `colour` and `targets` (#627).
    """
    from kennis.engine.pack.schema import read_yaml

    if not path.is_file():
        return TagStore()
    try:
        document = read_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise _unreadable(path, f"it is not YAML: {error}") from error
    if document is None:
        return TagStore()
    if not isinstance(document, dict):
        raise _unreadable(path, "it is not a mapping of tags to their targets")
    held: Tags = {}
    colours: dict[str, str] = {}
    for key, value in document.items():
        if not isinstance(key, str):
            raise _unreadable(path, f"the tag {key!r} is not a name")
        try:
            name = tag_name(key)
        except TagNameRefused as refused:
            raise _unreadable(path, str(refused)) from refused
        if name != key:
            raise _unreadable(path, f"the tag '{key}' is written as '{name}'")
        targets = value
        if isinstance(value, dict):
            targets, colour = _coloured(path, key, value)
            colours[name] = colour
        if targets is None:
            continue
        if not isinstance(targets, list):
            raise _unreadable(path, f"the tag '{key}' holds no list of targets")
        held[name] = tuple(_anchor(path, key, target) for target in targets)
    kept = {name: anchors for name, anchors in held.items() if anchors}
    return TagStore(
        tags=kept, colours={name: colours[name] for name in colours if name in kept}
    )


def _coloured(path: Path, name: str, value: dict[object, object]) -> tuple[object, str]:
    """A coloured tag's targets and colour."""
    unknown = set(value) - {_COLOUR_KEY, _TARGETS_KEY}
    if unknown:
        raise _unreadable(
            path, f"the tag '{name}' has {', '.join(sorted(map(str, unknown)))}"
        )
    if _TARGETS_KEY not in value:
        raise _unreadable(path, f"the tag '{name}' has a colour and no targets")
    colour = value.get(_COLOUR_KEY)
    if not isinstance(colour, str):
        raise _unreadable(path, f"the tag '{name}' has the colour {colour!r}")
    try:
        return value[_TARGETS_KEY], tag_colour(colour)
    except TagColourRefused as refused:
        raise _unreadable(path, str(refused)) from refused


def tag_colour(text: str) -> str:
    """`text` as a tag colour: one of `TAG_COLOURS`, or a hex colour as
    `#rrggbb` (a typed `#rgb` is widened), in lowercase; otherwise
    `TagColourRefused`.

    A hex colour is kept as typed; the window moves its lightness per theme
    until it can be seen (#629), so the file says what the person chose.
    """
    colour = text.strip().lower()
    if colour in TAG_COLOURS:
        return colour
    if _SHORT_HEX.fullmatch(colour):
        colour = "#" + "".join(digit * 2 for digit in colour[1:])
    if _HEX.fullmatch(colour):
        return colour
    raise TagColourRefused(
        f"'{text}' is not a tag colour: choose one of {', '.join(TAG_COLOURS)}, "
        "or a hex colour such as #1f5fd1"
    )


def is_hex_colour(colour: str) -> bool:
    return _HEX.fullmatch(colour) is not None


def colour_of(name: str, chosen: Mapping[str, str]) -> str:
    """The colour `name` is drawn in: the one chosen, or one of
    `TAG_COLOURS` derived from the name.

    crc32 rather than `hash`, which Python seeds afresh in every process,
    so a tag keeps its colour across windows and restarts.
    """
    if name in chosen:
        return chosen[name]
    return TAG_COLOURS[zlib.crc32(name.encode("utf-8")) % len(TAG_COLOURS)]


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


def written(held: Mapping[str, Sequence[Anchor]], *, colours: Mapping[str, str]) -> str:
    """`held` as the file's text: tags in order of name, targets in the
    order they were tagged, a coloured tag as a mapping. A tag with no
    targets is left out, and its colour with it.

    `colours` has no default: a writer that did not say which colours it
    keeps would drop every chosen colour on the next change.
    """
    document: dict[str, object] = {}
    for name in sorted(held):
        if not held[name]:
            continue
        targets = [_target(anchor) for anchor in held[name]]
        if name in colours:
            document[name] = {_COLOUR_KEY: colours[name], _TARGETS_KEY: targets}
        else:
            document[name] = targets
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
    collapsed = passage_words(text)
    if len(collapsed) <= _QUOTE_LENGTH:
        return collapsed
    cut = collapsed.rfind(" ", 0, _QUOTE_LENGTH + 1)
    return collapsed[: cut if cut > 0 else _QUOTE_LENGTH]


def passage_words(text: str) -> str:
    """A chunk's words as kennis quotes them: leading heading lines passed
    over, since a section's heading is not its passage's own words, and
    whitespace collapsed to single spaces."""
    lines = text.splitlines()
    while len(lines) > 1 and (
        not lines[0].strip() or lines[0].lstrip().startswith("#")
    ):
        lines = lines[1:]
    return _collapsed("\n".join(lines))


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


def rehinted(held: Mapping[str, Sequence[Anchor]], chunks: Sequence[Chunk]) -> Tags:
    """`held` with each passage's hint set to where it is placed among
    `chunks` now (#626).

    The nearest occurrence of repeated words is taken by the hint, so a hint
    left behind by several edits can pick the wrong one; rewritten after
    each, it follows its passage. A detached or unchecked passage keeps its
    hint, there being nothing better to say. Two targets of one tag placed
    at one chunk are one target, and the first is kept.
    """
    by_document = _by_document(chunks)
    changed: Tags = {}
    for name, anchors in held.items():
        kept: list[Anchor] = []
        for anchor in anchors:
            moved = anchor
            if anchor.chunk is not None:
                where = placed(anchor, by_document.get(anchor.document, ()))
                if isinstance(where, Placed) and where.chunk is not None:
                    moved = Anchor(anchor.document, where.chunk, anchor.quote)
            if not any(each.names_the_same(moved) for each in kept):
                kept.append(moved)
        changed[name] = tuple(kept)
    return changed


def tags_on(
    held: Mapping[str, Sequence[Anchor]], chunk: Chunk
) -> list[tuple[str, bool]]:
    """The tags `chunk` carries, in order of name, each with whether it is
    on the whole document.

    **The hint is trusted, with the words checked in the chunk itself**: a
    store's hints are set to where each passage is placed at every write
    and at every corpus index build (#626), which is the only time a
    chunk's number changes. A caller holding a store whose hints may be
    older - a project's, rewritten only when its tags change - rehints it
    in memory first.
    """
    words_here = _collapsed(chunk.text)
    carried: list[tuple[str, bool]] = []
    for name in sorted(held):
        own = [anchor for anchor in held[name] if anchor.document == chunk.document_id]
        if any(anchor.chunk is None for anchor in own):
            carried.append((name, True))
        elif any(
            anchor.chunk == chunk.chunk_index
            and (anchor.quote is None or _collapsed(anchor.quote) in words_here)
            for anchor in own
        ):
            carried.append((name, False))
    return carried


def _by_document(chunks: Sequence[Chunk]) -> dict[str, list[Chunk]]:
    by_document: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk.document_id, []).append(chunk)
    return by_document


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
    by_document = _by_document(chunks)
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
    "TAG_COLOURS",
    "Anchor",
    "Detached",
    "Placed",
    "Placement",
    "TagColourRefused",
    "TagNameRefused",
    "TagStore",
    "Tags",
    "TagsUnreadable",
    "Unchecked",
    "admitting",
    "colour_of",
    "is_hex_colour",
    "passage_words",
    "placed",
    "quote_of",
    "read_store",
    "read_tags",
    "rehinted",
    "split_tag_names",
    "tag_colour",
    "tag_name",
    "tags_on",
    "with_tags",
    "without_tags",
    "written",
]
