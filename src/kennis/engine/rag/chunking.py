"""Splitting a document into retrievable spans.

Chunks keep character offsets back into the original text, so a result can
say where it was found and that claim can be checked. They keep the nearest
preceding heading as a section label, and any image references in the span
resolved to files that exist.

**Chunking is block-aware.** A `markdown-it-py` parse locates the boundaries
of atomic blocks - tables, fenced code, display math, lists, headings,
blockquotes - and the packer never bisects one. Only prose is split, by a
sliding window snapped to whitespace. One over-long chunk beats half a table.

One departure from boepie, which this is otherwise a close port of: **the
headings come from the same parse as the blocks, not from a regular
expression over the raw text.** A regex cannot tell a heading from a `#`
comment at the start of a line inside a fenced code block, and kennis fences
an ingested source file with its language, so a corpus of notes made from
code is full of them. Treating one as a heading both mislabels the chunk and
splits the fence that the packer exists to keep whole - the block-awareness
was being defeated before the packer ever ran.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

from kennis.engine.rag.models import Chunk, Document

# Markdown image reference: `![alt](path)`, capturing the path.
_IMAGE_REFERENCE: Final = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# Used only to locate block boundaries, never to render or to walk inline
# content. "gfm-like" adds table recognition on top of CommonMark; linkify is
# disabled because it needs an optional dependency and no inline token is
# ever consulted. dollarmath adds a block-level `$$...$$` token.
_PARSER: Final = MarkdownIt("gfm-like").disable("linkify")
_PARSER.use(dollarmath_plugin)

# How far past a window's end to look for whitespace before giving up and
# cutting mid-word.
_SNAP_LOOKAHEAD: Final = 80


@dataclass(frozen=True, slots=True)
class ChunkParameters:
    """How a document is cut up, as a value something can hash.

    A value rather than module constants because the vector cache is keyed on
    the full derivation binding, and the chunk parameters are part of how a
    vector was derived. Reading them from a global would make the key
    unknowable at the point it is built.

    **`version` is not derivable from `size` and `overlap`.** Identical
    numbers run through a changed packing algorithm produce different chunks,
    so a cache keyed on the numbers alone would serve vectors for text that
    no longer exists. It is bumped by hand when the algorithm changes, which
    is a discipline rather than a mechanism - visible, rather than clever.
    """

    size: int = 1500
    overlap: int = 200
    version: int = 1


@dataclass(frozen=True, slots=True)
class _Block:
    """One top-level markdown block, as character offsets."""

    start: int
    end: int
    is_heading: bool
    # Everything except prose is atomic: the packer may never split it.
    is_atomic: bool
    # The heading's text, for a heading block.
    title: str | None = None


def chunk_document(
    document: Document, *, collection: str, parameters: ChunkParameters
) -> list[Chunk]:
    """Split `document` into chunks, section by section.

    `collection` is taken here rather than filled in afterwards by the index
    builder: a field that is a lie until someone remembers to correct it is a
    defect waiting for the caller who forgets.
    """
    text = document.text
    chunks: list[Chunk] = []

    for section_title, blocks in _sections(text):
        for start, end in _pack(blocks, text, parameters):
            span = text[start:end]
            if not span.strip():
                continue
            index = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{document.id}::{index}",
                    collection=collection,
                    document_id=document.id,
                    chunk_index=index,
                    text=span,
                    source_path=document.source_path,
                    char_start=start,
                    char_end=end,
                    section=section_title,
                    metadata={
                        **document.metadata,
                        "images": resolve_image_refs(span, document.base_path),
                    },
                )
            )
    return chunks


def resolve_image_refs(text: str, base_path: str | Path | None) -> list[str]:
    """Image references in `text` that resolve to files under `base_path`.

    Each reference is tried as written and again under an `images/`
    subdirectory, because a converter writes files there while emitting bare
    filenames. Order-preserving and de-duplicated. A reference that resolves
    to nothing is dropped rather than recorded, so a caller never has to
    check whether a recorded path exists.
    """
    if base_path is None:
        return []
    base = Path(base_path)
    resolved: list[str] = []
    for reference in _IMAGE_REFERENCE.findall(text):
        name = Path(reference).name
        for candidate in (base / reference, base / "images" / name):
            if candidate.exists():
                resolved.append(str(candidate))
                break
    return list(dict.fromkeys(resolved))


def _sections(text: str) -> list[tuple[str | None, list[_Block]]]:
    """The document's blocks, grouped under the heading that precedes them.

    A heading opens a section and belongs to it, so the heading's own text is
    chunked with the prose beneath it rather than orphaned. Blocks before the
    first heading form a section labelled None.
    """
    sections: list[tuple[str | None, list[_Block]]] = []
    title: str | None = None
    current: list[_Block] = []

    for block in _blocks(text):
        if block.is_heading:
            if current:
                sections.append((title, current))
            title = block.title
            current = [block]
            continue
        current.append(block)

    if current:
        sections.append((title, current))
    return sections


def _blocks(text: str) -> list[_Block]:
    """Every top-level block of `text`, as character offsets.

    Only tokens at nesting level 0 are considered, and only the opening or
    self-contained one: markdown-it already sets a container's `map` to span
    its whole content, so a table, list or blockquote is one block however
    deeply nested its interior is.
    """
    if not text.strip():
        return []

    offsets = _line_offsets(text)
    tokens = _PARSER.parse(text)
    blocks: list[_Block] = []

    for position, token in enumerate(tokens):
        if token.level != 0 or token.nesting == -1 or token.map is None:
            continue
        start_line, end_line = token.map
        start = offsets[start_line]
        end = offsets[end_line] if end_line < len(offsets) else len(text)
        is_heading = token.type == "heading_open"
        blocks.append(
            _Block(
                start=start,
                end=end,
                is_heading=is_heading,
                is_atomic=token.type != "paragraph_open",
                title=_heading_title(tokens, position) if is_heading else None,
            )
        )
    return blocks


def _heading_title(tokens: Sequence[Token], position: int) -> str | None:
    """The text of the heading opened at `position`, if it has any.

    markdown-it puts a heading's text in the `inline` token that follows its
    opening token, so this reads forward by one rather than re-reading the
    source text - which is the whole point of taking headings from the parse.
    """
    if position + 1 >= len(tokens):
        return None
    stripped = tokens[position + 1].content.strip()
    return stripped or None


def _line_offsets(text: str) -> list[int]:
    """The character offset each line starts at, plus a final `len(text)`.

    This is what turns markdown-it's `[start_line, end_line)` token maps into
    the character offsets every chunk's provenance is built on.

    **A deliberate `\\n` scan, never `str.splitlines`.** Python also breaks on
    `\\x0b \\x0c \\x1c \\x1d \\x1e \\x85`; markdown-it breaks only on `\\n`.
    A form feed - exactly what a PDF-to-markdown page break leaves behind -
    would desynchronise these offsets from markdown-it's line numbers and
    silently misplace every block boundary after it.
    """
    offsets = [0]
    position = 0
    while (newline := text.find("\n", position)) != -1:
        position = newline + 1
        offsets.append(position)
    if offsets[-1] != len(text):
        offsets.append(len(text))
    return offsets


def _pack(
    blocks: list[_Block], text: str, parameters: ChunkParameters
) -> list[tuple[int, int]]:
    """Pack blocks into windows, never bisecting an atomic one.

    Adjacent blocks merge into a run while the run fits, and the run flushes
    as soon as the next block would overflow it. A block oversized by itself
    is handled alone: an atomic one is kept whole, because one over-long
    chunk beats a bisected table or a bisected equation, and prose is the one
    thing the sliding window is allowed to cut.
    """
    windows: list[tuple[int, int]] = []
    run_start: int | None = None
    run_end = 0

    def flush() -> None:
        if run_start is not None:
            windows.append((run_start, run_end))

    for block in blocks:
        if block.end - block.start > parameters.size:
            flush()
            run_start = None
            if block.is_atomic:
                windows.append((block.start, block.end))
            else:
                windows.extend(_windows(block.start, block.end, text, parameters))
            continue
        if run_start is None:
            run_start = block.start
        elif block.end - run_start > parameters.size:
            flush()
            run_start = block.start
        run_end = block.end

    flush()
    return windows


def _windows(
    start: int, end: int, text: str, parameters: ChunkParameters
) -> list[tuple[int, int]]:
    """Sliding windows over `[start, end)`, each snapped to a word boundary."""
    if end - start <= parameters.size:
        return [(start, end)]

    step = max(1, parameters.size - parameters.overlap)
    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        stop = _snap_to_boundary(text, min(cursor + parameters.size, end), end)
        windows.append((cursor, stop))
        if stop >= end:
            break
        cursor += step
    return windows


def _snap_to_boundary(text: str, stop: int, end: int) -> int:
    """`stop` extended to the next whitespace, so a word is not cut in half."""
    limit = min(stop + _SNAP_LOOKAHEAD, end)
    for position in range(stop, limit):
        if text[position].isspace():
            return position
    return stop
