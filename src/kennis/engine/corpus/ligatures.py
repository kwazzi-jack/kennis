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

*Require the insertion to give back half of a ligature*: an `f` beside an
`f`, or an `i` or `l` straight after an `f` (see `_restores_a_ligature`;
until 2026-10-13 it was any of the three beside its own twin, which never
reached `fi` or `fl` damage and turned `modeling` into `modelling`). The
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
# Ends on a letter: a closing quote or a dash is the sentence's, and
# `'efect'` was looked up as `efect'`, which no vocabulary holds.
_TOKEN: Final = re.compile(r"[A-Za-z](?:[A-Za-z'-]*[A-Za-z])?")

# Where a PDF breaks a word across a line. Which codepoint appears depends on
# the font: U+FFFE is what pypdfium2 produced for one arXiv paper, U+00AD is
# the standard soft hyphen, U+FFFD is the replacement character another font
# yields, and a trailing hyphen before a newline is the plain-text form.
_BREAKS: Final = re.compile("[\\ufffe\\u00ad\\ufffd]|-\\s*\\n\\s*")

# Regions that are notation or literal text rather than prose. Changing a
# token inside one would change an equation or an identifier, which is a
# worse failure than leaving a misspelling in place. An address is literal
# text too: `[code](https://github.com/x/stuf-tool)` had its link rewritten
# to `stuff-tool`, which goes nowhere.
#
# Inline math by Pandoc's rule: the opening `$` is not followed by a space or
# a digit, the closing one is not preceded by a space or followed by a digit.
# Any two dollars on a line counted before, so "$5 for the efect, $10" kept
# everything between two prices from being repaired.
_PROTECTED: Final = re.compile(
    r"```.*?```|`[^`\n]*`|\$\$.*?\$\$|\$(?=[^\s\d$])[^$\n]*?(?<=\S)\$(?!\d)"
    r"|\]\([^)\n]*\)|<[a-z][a-z0-9+.-]*://[^>\n]*>|\b[a-z][a-z0-9+.-]*://\S+",
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

    **Closed explicitly.** A `PdfDocument` sits in a reference cycle, so
    an unclosed one holds the file until a collection happens to run -
    in the window, for as long as it is open, and on Windows the source
    cannot be moved meanwhile. One that reaches exit is listed on stderr
    by pypdfium2, after a `corpus add` that succeeded. Closing the
    document closes its pages and text pages with it.
    """
    words: set[str] = set()
    with pypdfium2.PdfDocument(pdf_path) as document:
        for page in document:
            text = page.get_textpage().get_text_range()
            words.update(match.group().lower() for match in _TOKEN.finditer(text))
            words.update(
                match.group().lower()
                for match in _TOKEN.finditer(_BREAKS.sub("", text))
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
        ((word, position),) = candidates
        pieces.append(text[cursor : match.start()])
        pieces.append(_matching_case(token, word, position))
        cursor = match.end()
        repaired += 1
    pieces.append(text[cursor:])
    return "".join(pieces), repaired


def _candidates(token: str, vocabulary: frozenset[str]) -> list[tuple[str, int]]:
    """Vocabulary words reachable by restoring one ligature half, each with
    where the letter went.

    More than one word means the evidence does not name a repair, and
    guessing between them is the thing this pass must never do.
    """
    found: dict[str, int] = {}
    lowered = token.lower()
    for position in range(len(lowered) + 1):
        for letter in _LIGATURE_LETTERS:
            if not _restores_a_ligature(lowered, position, letter):
                continue
            candidate = lowered[:position] + letter + lowered[position:]
            if candidate in vocabulary:
                found.setdefault(candidate, position)
    return sorted(found.items())


def _restores_a_ligature(lowered: str, position: int, letter: str) -> bool:
    """Whether inserting `letter` here gives back half of a ligature.

    Two ways, and only two. An `f` beside an `f`: `ff`, `ffi` or `ffl` lost
    one, as `diferent` did. An `i` or an `l` straight after an `f`: `fi` or
    `fl` lost its second letter, as `signifcant` and `refect` did.

    **An `i` or `l` beside its own twin is not one.** There is no `ll` or
    `ii` ligature, so doubling them only ever turned one spelling into
    another - `modeling` into `modelling`, `labeled` into `labelled` - while
    the real `fi` and `fl` damage went unrepaired. And `column` would take an
    `s` next to an `n`, which is a different word, not this damage.
    """
    before = lowered[position - 1 : position] if position else ""
    if letter == "f":
        return before == "f" or lowered[position : position + 1] == "f"
    return before == "f"


def _matching_case(original: str, repaired: str, position: int) -> str:
    """The repaired spelling, wearing the original's capitalisation letter
    by letter, and the restored letter its neighbour's.

    Letter by letter, because `capitalize()` lowered everything after the
    first: `EficientNet` became `Efficientnet`.
    """
    # A capital only between capitals: `EficientNet` restores a small `f`
    # after its capital `E`, and `DIFERENT` a capital one.
    beside = original[max(position - 1, 0) : position + 1]
    inserted = repaired[position]
    upper = bool(beside) and beside.isupper()
    cased = (
        original[:position]
        + (inserted.upper() if upper else inserted)
        + original[position:]
    )
    return cased
