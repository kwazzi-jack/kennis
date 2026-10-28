"""`kennis pack format`: every entry of a pack file in kennis's form (#558).

What `text.with_entry` does to one entry kennis changes, done to all of
them: each a mapping in braces with one key per line in `FIELD_ORDER`, a
paper's authors a list, an identifier spelled the one way, and a blank line
between entries. Comments and blank lines between entries stay; a comment
inside an entry does not. A file whose authors kennis wrote as one string,
before #558, does not validate, so the entries are read as YAML reads them
and only the result is validated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import yaml
from yaml.nodes import SequenceNode

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.schema import authors_from_line, load_pack
from kennis.engine.pack.text import (
    Written,
    composed,
    dash_of,
    entry_written,
    last_line,
    node_at,
    read_pack_text,
    with_entry,
)

_SECTIONS: Final = (
    ("corpus", "literature"),
    ("corpus", "docs"),
    ("corpus", "notes"),
    ("context",),
)


def format_pack(path: Path) -> bool:
    """Write the pack at `path` in kennis's form, and whether that changed
    it; a file already so is not opened for writing. Raises `PackInvalid`
    when it does not parse, or does not validate once formatted, with
    nothing written."""
    text = read_pack_text(path)
    try:
        formatted = formatted_text(text)
    except yaml.YAMLError as error:
        raise PackInvalid(f"this is not YAML: {error}") from error
    if formatted == text:
        return False
    load_pack(formatted)
    path.write_text(formatted, encoding="utf-8", newline="\n")
    return True


def formatted_text(text: str) -> str:
    for section in _SECTIONS:
        node = node_at(composed(text), section)
        if not isinstance(node, SequenceNode) or node.flow_style:
            continue
        # From the last, so an entry's lines are where the parse said.
        for index in reversed(range(len(node.value))):
            converted = _converted(entry_written(text, section, index))
            text = with_entry(text, section, index, converted)
        text = _set_apart(text, section)
    return text


def _converted(item: Written) -> Written:
    """`authors` as one BibTeX string, as kennis wrote it before #558, made
    the list a pack holds."""
    return [
        (
            key,
            authors_from_line(value)
            if key == "authors" and isinstance(value, str)
            else value,
        )
        for key, value in item
    ]


def _set_apart(text: str, section: tuple[str, ...]) -> str:
    """A blank line after each entry of `section` that has nothing but the
    next entry below it; a blank line or a comment already there stays."""
    node = node_at(composed(text), section)
    assert isinstance(node, SequenceNode)
    lines = text.splitlines(keepends=True)
    for before, after in reversed(list(zip(node.value, node.value[1:], strict=False))):
        end = last_line(before, lines)
        start, _ = dash_of(text, after)
        if start == end + 1:
            lines.insert(end + 1, "\n")
    return "".join(lines)


__all__ = ["format_pack", "formatted_text"]
