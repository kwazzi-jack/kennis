"""Splitting a markdown body into the parts a front end styles differently.

Three kinds: **prose**, a **fence** line, and the **code** between a pair of
them. The fences are blocks of their own rather than being consumed, because
the terminal shows the characters the corpus holds - a reader and an agent
looking at the same document see the same bytes - and because that gives the
property this module is really defined by:

    "".join(block.text for block in split_blocks(text)) == text

for every input, including the awkward ones. A renderer that drops a newline
turns a document into a different document.

**A code block that names no language is not guessed at.** Guessing was
measured against a real corpus of 262 unlabelled fences and produced MySQL,
GDScript, scdoc, Carbon, Transact-SQL, Objective-C, Tera Term macro and
verilog for content that is plainly YAML and shell - not one usable answer.
`guess_lexer` scores the text against every lexer and returns the best, so it
always answers, and on this corpus it was always wrong.

`detected_language` is the other thing, and the distinction is the point of
this module: it *parses*, so it answers only for text that is a document of
that kind, and says nothing otherwise. On the same corpus it identifies 95 of
137 unlabelled blocks as YAML and makes no other claim. The 42 it declines
are YAML fragments with undefined anchors - a miss, not a mistake. Concern
#214.

The fence rules follow commonmark closely enough for real documents: a fence
is a line of its own made of at least three backticks or tildes, optionally
indented by up to three spaces, and it is closed only by a line of the same
character that is at least as long. That last rule is the reason four-backtick
fences exist, and getting it wrong swallows the rest of a document.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Literal

import yaml
from yaml.nodes import MappingNode, Node, SequenceNode

type BlockKind = Literal["prose", "fence", "code"]

# At most three spaces of indent, then three or more of one fence character,
# then an optional info string. `\S+` for the language, because commonmark
# allows a whole info string and only the first word names the lexer.
_FENCE: Final = re.compile(r"^(?P<indent> {0,3})(?P<mark>`{3,}|~{3,})(?P<info>[^\n]*)$")


@dataclass(frozen=True, slots=True)
class Block:
    """One run of a markdown body, and what kind of thing it is.

    `text` is the original slice, newlines and all, so the blocks of a
    document concatenate back into it. `language` is the first word of a
    fence's info string, carried on the opening fence and on the code it
    introduces, and empty when there was none - which is a fact about the
    document, not a gap to fill in.
    """

    kind: BlockKind
    text: str
    language: str = ""


def split_blocks(text: str) -> list[Block]:
    """`text` as prose, fence and code blocks, in order."""
    blocks: list[Block] = []
    prose: list[str] = []
    code: list[str] = []
    # The opening fence's marker while a block is open, None while it is not.
    open_mark: str | None = None
    language = ""

    def flush(buffer: list[str], kind: BlockKind, tag: str = "") -> None:
        if buffer:
            blocks.append(Block(kind=kind, text="".join(buffer), language=tag))
            buffer.clear()

    for line in text.splitlines(keepends=True):
        found = _FENCE.match(line.rstrip("\n"))
        if open_mark is None:
            if found is None:
                prose.append(line)
                continue
            flush(prose, "prose")
            open_mark = found["mark"]
            language = found["info"].strip().split(" ")[0] if found["info"] else ""
            blocks.append(Block(kind="fence", text=line, language=language))
            continue
        # Inside a block: only a fence of the same character and at least the
        # same length closes it. A shorter or different one is content, which
        # is what makes ```` able to contain ```.
        if (
            found is not None
            and found["mark"][0] == open_mark[0]
            and len(found["mark"]) >= len(open_mark)
            and not found["info"].strip()
        ):
            flush(code, "code", language)
            blocks.append(Block(kind="fence", text=line, language=language))
            open_mark = None
            language = ""
            continue
        code.append(line)

    # An unterminated fence: a truncated document is still a document, and
    # everything after the opening fence is code.
    flush(code, "code", language)
    flush(prose, "prose")
    return blocks


def detected_language(text: str) -> str:
    """The language `text` can be shown to be, or `""`.

    Only two answers are possible, because only two can be settled by parsing
    rather than by resemblance. JSON is tried first: it is a subset of YAML,
    so the YAML test would accept it and pygments would then lex it as the
    wrong thing.

    A caller uses this only for a block whose fence named no language. A
    fence that said `text` meant `text`.
    """
    if not text.strip():
        return ""
    if _is_json_document(text):
        return "json"
    if _is_yaml_document(text):
        return "yaml"
    return ""


def _is_json_document(text: str) -> bool:
    try:
        value = json.loads(text)
    except ValueError:
        return False
    # `json.loads("5")` succeeds. A scalar is a value, not a document.
    return isinstance(value, dict | list)


def _is_yaml_document(text: str) -> bool:
    """Whether `text` parses as YAML *and* has structure inside it.

    `compose` is used rather than `safe_load` because only the shape is being
    asked about: it builds a node graph and constructs no Python values, so
    an alias-expansion payload in a converted third-party document costs what
    its bytes cost.

    The nesting requirement is what separates a document from a paragraph.
    `Note: this matters.` on two lines is a valid two-key mapping, and a code
    fence can hold prose. Requiring one value to be a mapping or a sequence
    rejects it, and on the real corpus rejected nothing else: 95 of 137 with
    the requirement and without it.
    """
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return False
    return _has_nesting(node)


def _has_nesting(node: Node | None) -> bool:
    if isinstance(node, MappingNode):
        return any(
            isinstance(value, MappingNode | SequenceNode) for _, value in node.value
        )
    if isinstance(node, SequenceNode):
        return any(isinstance(value, MappingNode) for value in node.value)
    return False


__all__ = ["Block", "BlockKind", "detected_language", "split_blocks"]
