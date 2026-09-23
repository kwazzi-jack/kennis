"""Repairing ligature damage against the PDF's own text layer.

MinerU resolves an `ff`, `fi` or `fl` ligature glyph to one character instead
of two, so `different` is stored as `diferent`. That is a retrieval defect,
not a cosmetic one: BM25 tokenises what is stored, so a search for
`different` cannot match it, the dense leg embeds a misspelling, and a
reindex does not repair it because the text on disk is already wrong.
Concerns #135, #136.

pypdfium2 reads the same PDF correctly, costs 0.7 ms per page and no GPU, and
so can serve as a reference for what the document actually says.

**Two constraints, and the pass is unsafe without either.**

*Join the line-break glyph when building the vocabulary.* This is how a PDF
hyphenates across a line, and pypdfium2 surfaces it as U+FFFE, U+00AD or
U+FFFD depending on the font. Without joining, `numerical` enters the
vocabulary as `numer` and `ical`, so a correctly converted word looks absent
and becomes a repair target. Joining recovered 47 words on a 19-page paper
and cut the unrepairable list from 48 to 3.

*Require the insertion to be a ligature letter beside its own twin.* The
reference is authoritative about what the PDF says, not about what is
correct, and it is **incomplete** - 4.5% of the correct words in a known-good
conversion were absent from it, because pypdfium2 cannot read text inside a
figure. So absence alone is weak evidence. This constraint is not spelling
correction; it is a statement about what the damage is, so the pass only ever
changes a word that looks exactly like a ligature that lost half of itself.
Concern #152.

Without the second constraint, the pass made 6 wrong repairs on one clean
conversion and 21 on another, including `behavior` -> `behaviour`,
`trough` -> `through`, and two that copied the authors' own misspellings into
text that was correct. Concerns #151, #153.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pypdfium2

# A token is alphabetic with internal hyphens or apostrophes. Numbers,
# symbols and LaTeX are not words and are never touched.
_TOKEN: Final = re.compile(r"[A-Za-z][A-Za-z'-]*")

# Where a PDF breaks a word across a line. Which codepoint appears depends on
# the font: U+FFFE is what pypdfium2 produced for one arXiv paper, U+00AD is
# the standard soft hyphen, U+FFFD is the replacement character another font
# yields, and a trailing hyphen before a newline is the plain-text form.
_BREAKS: Final = re.compile("[\\ufffe\\u00ad\\ufffd]|-\\s*\\n\\s*")

# Regions that are notation or literal text rather than prose. Changing a
# token inside one would change an equation or an identifier, which is a
# worse failure than leaving a misspelling in place.
_PROTECTED: Final = re.compile(
    r"```.*?```|`[^`\n]*`|\$\$.*?\$\$|\$[^$\n]*\$",
    re.DOTALL,
)

# The Latin ligature set is `ff`, `fi`, `fl`, `ffi` and `ffl`, so the
# character a converter drops is always one of these.
_LIGATURE_LETTERS: Final = "fil"

# Below this length a token is left alone. Short words are dense in the space
# of one-insertion neighbours, and a genuine short token is usually a symbol.
_MINIMUM_LENGTH: Final = 4


def text_layer_vocabulary(pdf_path: Path) -> frozenset[str]:
    """Every word the PDF's own text layer contains, lower-cased.

    Streamed page by page: the word set is what is kept, never the whole
    text. Both the joined form and its halves are kept, because a half is
    often a real word elsewhere in the same document.
    """
    words: set[str] = set()
    document = pypdfium2.PdfDocument(pdf_path)
    for page in document:
        text = page.get_textpage().get_text_range()
        words.update(match.group().lower() for match in _TOKEN.finditer(text))
        words.update(
            match.group().lower() for match in _TOKEN.finditer(_BREAKS.sub("", text))
        )
    return frozenset(words)


def repair_ligatures(text: str, vocabulary: frozenset[str]) -> tuple[str, int]:
    """The text with its ligature damage repaired, and how many were.

    The count is worth carrying: it is a direct per-document measure of how
    badly a converter handled this document, which is the number that would
    have shown #135 on the day it was introduced.
    """
    spans = [(span.start(), span.end()) for span in _PROTECTED.finditer(text)]
    pieces: list[str] = []
    cursor = 0
    repaired = 0
    for match in _TOKEN.finditer(text):
        token = match.group()
        if len(token) < _MINIMUM_LENGTH or token.lower() in vocabulary:
            continue
        if any(match.start() >= low and match.end() <= high for low, high in spans):
            continue
        candidates = _candidates(token, vocabulary)
        if len(candidates) != 1:
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(_matching_case(token, candidates[0]))
        cursor = match.end()
        repaired += 1
    pieces.append(text[cursor:])
    return "".join(pieces), repaired


def _candidates(token: str, vocabulary: frozenset[str]) -> list[str]:
    """Vocabulary words reachable by restoring one ligature half.

    More than one means the evidence does not name a repair, and guessing
    between them is the thing this pass must never do.
    """
    found: set[str] = set()
    lowered = token.lower()
    for position in range(len(lowered) + 1):
        for letter in _LIGATURE_LETTERS:
            if not _doubles(lowered, position, letter):
                continue
            candidate = lowered[:position] + letter + lowered[position:]
            if candidate in vocabulary:
                found.add(candidate)
    return sorted(found)


def _doubles(lowered: str, position: int, letter: str) -> bool:
    """Whether inserting `letter` here puts it beside its own twin.

    This is what separates the damage from a coincidence. `diferent` takes an
    `f` next to an `f`; `column` would take an `s` next to an `n`, which is
    not a ligature losing half of itself but a different word.
    """
    before = lowered[position - 1 : position] if position else ""
    return before == letter or lowered[position : position + 1] == letter


def _matching_case(original: str, repaired: str) -> str:
    """The repaired spelling, wearing the original's capitalisation."""
    if original.isupper():
        return repaired.upper()
    if original[:1].isupper():
        return repaired.capitalize()
    return repaired
