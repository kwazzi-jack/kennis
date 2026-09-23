"""Making a converter's output actually be markdown.

What a converter hands back is stored, indexed and chunked as-is, so HTML
left in it is not cosmetic. MinerU writes tables as raw HTML: on a 17-page
MNRAS paper that was 15% of the stored characters, 2722 `<td>` and 260 `<tr>`
across two tables. BM25 tokenises what is stored, so the index fills with
`td` and `tr`; the dense leg embeds them; and a chunk boundary can fall
inside a row, leaving cells with no header above them. Concern #154.

Applied to **both** backends. Tables are a MinerU defect, but `<sup>` and
`<sub>` come from both, and what is stored should be markdown regardless of
who produced it - otherwise the same document indexes differently depending
on a setting.

**Only the tags that were measured are handled.** Stripping every tag would
silently rewrite text nobody has looked at, and a converter is free to emit
something meaningful tomorrow. An unrecognised tag is left exactly as it is.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

# Code is quoted rather than composed: a `<table>` inside a fenced block is
# being shown, not used, and converting it would rewrite an example.
_CODE: Final = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)

# Mathematics is protected from the `<sup>`/`<sub>` pass but **not** from the
# table pass. Maths lives inside table cells - one real MinerU table had
# `$F _ { \mathrm { m e d } }$` in a heading cell - and splitting the text at
# a maths span put the `<table>` and its `</table>` into different fragments,
# so the table matched neither and 1270 `<td>` reached the corpus. A table
# never legitimately appears inside `$...$`, so the asymmetry is safe.
_CODE_OR_MATHS: Final = re.compile(
    r"```.*?```|`[^`\n]*`|\$\$.*?\$\$|\$[^$\n]*\$",
    re.DOTALL,
)

_TABLE: Final = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_ROW: Final = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL: Final = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_SUPERSCRIPT: Final = re.compile(r"<sup[^>]*>(.*?)</sup>", re.DOTALL | re.IGNORECASE)
_SUBSCRIPT: Final = re.compile(r"<sub[^>]*>(.*?)</sub>", re.DOTALL | re.IGNORECASE)


def normalise_markdown(text: str) -> str:
    """Convert the HTML a converter left behind into markdown.

    Two passes, because they need different things held aside. Tables are
    converted first, protected only from code; then superscripts and
    subscripts, protected from code and mathematics.
    """
    text = _outside(text, _CODE, _convert_tables)
    return _outside(text, _CODE_OR_MATHS, _convert_scripts)


def _convert_tables(text: str) -> str:
    return _TABLE.sub(lambda match: _as_pipe_table(match.group(1)), text)


def _convert_scripts(text: str) -> str:
    text = _SUPERSCRIPT.sub(lambda match: "^" + match.group(1).strip(), text)
    return _SUBSCRIPT.sub(lambda match: "_" + match.group(1).strip(), text)


def _outside(
    text: str, protected: re.Pattern[str], transform: Callable[[str], str]
) -> str:
    """Apply `transform` to everything that is not a protected span."""
    pieces: list[str] = []
    cursor = 0
    for span in protected.finditer(text):
        pieces.append(transform(text[cursor : span.start()]))
        pieces.append(span.group())
        cursor = span.end()
    pieces.append(transform(text[cursor:]))
    return "".join(pieces)


def _as_pipe_table(body: str) -> str:
    """One `<table>`'s innards as a markdown pipe table.

    An empty table becomes nothing at all: leaving the tags would keep the
    noise this module exists to remove, and a table with no rows carries
    nothing a reader or an index wants.
    """
    rows = [
        [_as_cell(cell) for cell in _CELL.findall(row)] for row in _ROW.findall(body)
    ]
    rows = [row for row in rows if row]
    if not rows:
        return ""

    # MinerU's rows are not guaranteed to be the same length. A short row
    # would put its cells under the wrong headings, so every row is padded
    # to the widest.
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    lines = ["| " + " | ".join(padded[0]) + " |"]
    # Without the separator a pipe table is not a table: it renders as a run
    # of text with pipes in it, which is worse than the HTML was.
    lines.append("| " + " | ".join(["---"] * width) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)


def _as_cell(content: str) -> str:
    """One cell's text, safe to put between pipes.

    A pipe row is one line and uses `|` as its own delimiter, so a cell can
    contain neither a newline nor a bare pipe.
    """
    inner = _outside(content, _CODE_OR_MATHS, _convert_scripts)
    inner = _outside(inner, _CODE_OR_MATHS, lambda part: re.sub(r"<[^>]+>", "", part))
    inner = re.sub(r"\s+", " ", inner).strip()
    return inner.replace("|", "\\|")
