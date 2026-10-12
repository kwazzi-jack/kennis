"""A hit's snippet, rendered rather than quoted, with the query marked.

**Why the window builds its own instead of using `rendered_hit`'s.**
`render/hits.py` hands every front end the same snippet string, and
that being the same string is what makes `kennis search` a faithful
proxy for what an agent sees (concern #297). A terminal has a
styling layer over plain text, so leaving markdown markers where
they stand is right there; a browser has a markup layer instead, and
the same decision put literal `##` and `[[35](https://...)]` on the
page. Concern #336.

So #297 narrows rather than lapses: `headline` and `detail` stay
byte-identical across front ends, and `body` becomes the same source
text rendered for its medium. `tests/test_gui_snippet.py` asserts
that every word the window shows appears in the command line's
snippet, in order - content may not drift, punctuation may.

**Why not simply render the snippet string.** `snippet_of` collapses
the whitespace before truncating, so by the time there is a string
to render, `## V Inference Methodology` and the paragraph after it
are one line and a markdown parse makes a heading of the whole
thing. The structure has to be read from the chunk's own text, which
is what this does.

**Why marking happens before anything becomes a tag.** A query is a
person's words and reaches this as a pattern. Marking finished HTML
for a query of "class" would rewrite `class="basis"`, and one of
"em" would eat the emphasis. Text runs are marked, escaped, and only
then wrapped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from html import escape
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

from kennis.render.html import (
    marked_text,
    query_pattern,
    to_html,
    without_empty_options,
)

# The same default `render/words.py::snippet_of` uses, so the two
# front ends cut at about the same place even though one counts
# source characters and the other counts characters the reader sees.
_SNIPPET_CHARACTERS: Final = 280

_MATHS_INLINE: Final = frozenset({"math_inline", "math_inline_double"})
_MATHS_BLOCKS: Final = frozenset({"math_block", "math_block_label"})

# Inline markdown that survives into a snippet. A snippet is prose,
# so a block element has nothing to be: the structure was flattened
# when the chunk was cut down to a few lines.
_KEPT: Final[dict[str, str]] = {
    "em_open": "<em>",
    "em_close": "</em>",
    "strong_open": "<strong>",
    "strong_close": "</strong>",
    "code_inline": "<code>",
}


# **Everything is inline in a snippet, including a display
# equation.** A snippet is one paragraph of prose; KaTeX's display
# mode produces a block element, which would break the sentence
# quoting it. So a `math_block` is shown inline rather than in
# display mode - and shown at all, which it was not: `_runs` walks
# `inline` tokens and a block equation is a leaf block token, so
# without a branch of its own it contributed nothing.
_MATHS_CLASS: Final = "math inline"


@dataclass(frozen=True, slots=True)
class _Run:
    """A piece of the snippet: text to escape, a tag to emit, or TeX.

    Kept apart so truncation can count only what the reader sees and
    marking can touch only what the reader reads.

    **TeX is a third kind because it is neither.** It is escaped like
    text, but it must not be marked - a `<mark>` inside an expression
    is markup KaTeX will render or refuse - and it must not be cut,
    because half an expression is a parse error where the whole would
    have rendered.
    """

    text: str
    tag: str | None = None
    maths: str | None = None


def marked_snippet(
    chunk: str, *, terms: Sequence[str], limit: int = _SNIPPET_CHARACTERS
) -> str:
    """One hit's text as HTML, cut to `limit` visible characters.

    `terms` are the reader's own words, marked where they occur whole
    and regardless of case. Nothing is stemmed: the index stems and
    this does not, so a search for "calibration" will not mark
    "calibrate". Prefix-matching to fix that would also mark
    "calibrate" inside "recalibrated", which claims a match the
    search did not make.
    """
    runs = _truncated(list(_runs(_tokens(chunk))), limit)
    pattern = query_pattern(terms)
    return "".join(_rendered(runs, pattern))


# How much of the window sits before the first match, when the match is
# too far in for the window to start at the top. Enough for the start of
# its sentence, usually, and little enough that the match is in the first
# line a closed passage shows.
_LEAD_CHARACTERS: Final = 60


@dataclass(frozen=True, slots=True)
class Passage:
    """A hit's chunk twice over: the window a closed passage shows, and
    the whole of it as blocks, which an opened one shows in its place.

    `window` is inline - the snippet, placed so the first match is in
    it - and `cut_before` and `cut_after` say whether text was left out
    on either side, which is where its ellipses go. `whole` is the chunk
    as the document renderer draws it, tables and all, with the same
    words marked. The page shows one or the other, never both, so no
    text is on it twice (Brian, 2026-10-12, after #415).
    """

    window: str
    whole: str
    cut_before: bool
    cut_after: bool


def passage_of(
    chunk: str, *, terms: Sequence[str], limit: int = _SNIPPET_CHARACTERS
) -> Passage:
    """The chunk's window of about `limit` visible characters, and the
    whole chunk.

    The window starts at the top unless the first match would fall
    outside it, in which case it starts a short lead before the match.
    The same runs `marked_snippet` reads, so the maths and marking rules
    are the same ones and TeX is never cut.
    """
    runs = list(_runs(_tokens(chunk)))
    pattern = query_pattern(terms)
    start = _window_start(runs, pattern, limit)
    before, rest = _split(runs, start)
    window, after = _split(rest, limit)
    return Passage(
        window="".join(_rendered(window, pattern)),
        whole=to_html(chunk, terms=terms),
        cut_before=_shows_text(before),
        cut_after=_shows_text(after),
    )


def _shows_text(runs: Sequence[_Run]) -> bool:
    return any(run.tag is None and run.text.strip() for run in runs)


def _window_start(
    runs: Sequence[_Run], pattern: re.Pattern[str] | None, limit: int
) -> int:
    """Where the window begins, in characters the reader sees."""
    if pattern is None:
        return 0
    seen = 0
    for run in runs:
        if run.tag is not None:
            continue
        if run.maths is None:
            found = pattern.search(run.text)
            if found is not None:
                at = seen + found.start()
                # A match the top-anchored window already shows whole
                # needs no move, and moving it would hide the opening.
                if at + len(found.group(0)) <= limit:
                    return 0
                return max(0, at - _LEAD_CHARACTERS)
        seen += len(run.text)
    return 0


def _split(runs: Sequence[_Run], offset: int) -> tuple[list[_Run], list[_Run]]:
    """Cut the runs at a word boundary at or before `offset` visible
    characters, keeping each side balanced.

    TeX is never cut: an expression that straddles the offset goes
    whole to the second side, for the reason `_truncated` gives. A tag
    open at the cut is closed on the first side and opened again on the
    second.
    """
    # Nothing before the start, not an empty pair of tags: a heading's
    # `<strong></strong>` is a non-empty string, and a page asks whether
    # a part is empty to decide whether there is anything to open.
    if offset <= 0:
        return [], list(runs)
    head: list[_Run] = []
    tail: list[_Run] = []
    opened: list[str] = []
    seen = 0
    cut = False
    for run in runs:
        if cut:
            tail.append(run)
            continue
        if run.tag is not None:
            head.append(run)
            if run.tag.startswith("</"):
                if opened:
                    opened.pop()
            else:
                opened.append(run.tag)
            continue
        if seen + len(run.text) <= offset:
            seen += len(run.text)
            head.append(run)
            continue
        cut = True
        room = offset - seen
        if run.maths is None and " " in run.text[:room]:
            boundary = run.text.rindex(" ", 0, room) + 1
            head.append(_Run(run.text[:boundary]))
            remainder = _Run(run.text[boundary:])
        else:
            remainder = run
        head.extend(_Run("", f"</{tag[1:]}") for tag in reversed(opened))
        tail.extend(_Run("", tag) for tag in opened)
        tail.append(remainder)
    return head, tail


def _tokens(chunk: str) -> list[Token]:
    # A parser of its own rather than `render/html.py`'s: this one
    # wants no fences and no images, because neither can be shown in
    # four lines of prose. Tables are parsed so that their cells can be
    # read as text: left to the paragraph rule, a table arrived as a
    # row of pipes and `| --- |` (Brian, 2026-10-12).
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
    parser.enable("table")
    # The same protection `render/html.py` has, for the same reason
    # and by the same route. Two parsers is deliberate - concern
    # #336 - but the maths rule is not one of the things they should
    # differ about, and for one unit they did: a snippet showed
    # `$\mathsf{B}$` where the document showed the symbol. Concern
    # #376.
    parser.use(dollarmath_plugin, double_inline=True)
    return parser.parse(chunk)


def _runs(tokens: Sequence[Token]) -> Iterator[_Run]:
    """The inline content of every block, in order, blocks separated.

    A link contributes its text and not its address. `[[35](https://
    example.org)]` is a citation in this corpus: the number is what a
    reader wants and the URL is the noise this exists to remove. An
    anchor would also put an outbound path in a list of results,
    which is the shape `render/html.py` refuses for figures.
    """
    first = True
    heading = False
    in_cell = False
    cells_in_row = 0
    rows_in_table = 0
    for token in tokens:
        if token.type == "heading_open":
            heading = True
            continue
        # A table is read across: its cells apart, its rows apart, an
        # empty cell adding nothing. Each separator is a space in an
        # element the stylesheet draws a mark beside, so no character
        # outside the corpus's own text is added.
        if token.type == "table_open":
            rows_in_table = 0
            continue
        if token.type == "tr_open":
            cells_in_row = 0
            continue
        if token.type in _CELL_OPENS:
            in_cell = True
            continue
        if token.type in _CELL_CLOSES:
            in_cell = False
            continue
        if in_cell and token.type == "inline":
            if not _visible(token):
                continue
            if cells_in_row:
                yield from _gap("cell-gap")
            elif rows_in_table:
                yield from _gap("row-gap")
            elif not first:
                yield _Run(" ")
            if not cells_in_row:
                rows_in_table += 1
            cells_in_row += 1
            first = True
        if token.type in _MATHS_BLOCKS:
            if not first:
                yield _Run(" ")
            first = False
            yield _Run(without_empty_options(token.content), maths=_MATHS_CLASS)
            continue
        if token.type != "inline" or token.children is None:
            continue
        if not first:
            yield _Run(" ")
        first = False
        # **A heading carries its own weight and adds no characters.**
        # Flattening the blocks ran a section title into the
        # paragraph after it - "Methodology To quantify the
        # performance" - and the `##` that used to mark the boundary
        # is exactly what this unit removes. A separator would be
        # text the corpus does not contain; bold is not.
        if heading:
            yield _Run("", "<strong>")
        for child in token.children:
            if child.type == "text":
                yield _Run(child.content)
            elif child.type == "code_inline":
                yield _Run("", "<code>")
                yield _Run(child.content)
                yield _Run("", "</code>")
            elif child.type in _MATHS_INLINE:
                yield _Run(without_empty_options(child.content), maths=_MATHS_CLASS)
            elif child.type in _KEPT:
                yield _Run("", _KEPT[child.type])
            elif child.type == "softbreak" or child.type == "hardbreak":
                yield _Run(" ")
        if heading:
            yield _Run("", "</strong>")
            heading = False


def _truncated(runs: list[_Run], limit: int) -> list[_Run]:
    """Cut to `limit` characters of visible text, at a word boundary.

    **On the runs, not on the finished HTML.** A cut in the string
    lands inside `<em>` and carries an unclosed element into
    everything after it on the page. Cutting here means every tag
    opened before the cut is still closed after it, because the
    closing runs are kept.
    """
    seen = 0
    kept: list[_Run] = []
    cut = False
    for run in runs:
        if run.tag is not None:
            kept.append(run)
            continue
        if run.maths is not None:
            # All or nothing. `\left(\begin{array}` with nothing
            # closing it is a parse error where the whole expression
            # would have rendered, so an expression that does not fit
            # ends the snippet instead of being bisected.
            if seen + len(run.text) <= limit:
                seen += len(run.text)
                kept.append(run)
                continue
            kept.append(_Run("..."))
            cut = True
            break
        if seen + len(run.text) <= limit:
            seen += len(run.text)
            kept.append(run)
            continue
        room = limit - seen
        head = run.text[:room]
        spaced = head.rsplit(" ", 1)[0] if " " in head else head
        kept.append(_Run(f"{spaced.rstrip()} ..."))
        cut = True
        break
    if not cut:
        return kept
    # Everything after the cut is dropped except the tags that were
    # already open, which have to be closed in reverse.
    opened = [
        run.tag for run in kept if run.tag is not None and not run.tag.startswith("</")
    ]
    closed = [
        run.tag for run in kept if run.tag is not None and run.tag.startswith("</")
    ]
    for tag in reversed(opened[len(closed) :]):
        kept.append(_Run("", f"</{tag[1:]}"))
    return kept


_CELL_OPENS: Final = frozenset({"th_open", "td_open"})
_CELL_CLOSES: Final = frozenset({"th_close", "td_close"})


def _gap(kind: str) -> Iterator[_Run]:
    # Opened and closed as two runs, so a cut between them is balanced
    # like any other element. The space is what separates the words for
    # anything reading the text; the stylesheet draws the mark.
    yield _Run("", f'<span class="{kind}">')
    yield _Run(" ")
    yield _Run("", "</span>")


def _visible(token: Token) -> bool:
    return any(child.content.strip() for child in token.children or ())


def _rendered(runs: Sequence[_Run], pattern: re.Pattern[str] | None) -> Iterator[str]:
    for run in runs:
        if run.tag is not None:
            yield run.tag
        elif run.maths is not None:
            # Escaped, never marked: `<`, `>` and `&` are all
            # ordinary in TeX and all markup here, and the reader's
            # term inside an expression is a symbol rather than a
            # word they were looking for.
            yield f'<span class="{run.maths}">{escape(run.text)}</span>'
        elif pattern is None:
            yield escape(run.text)
        else:
            yield marked_text(run.text, pattern)


def terms_of(question: str) -> tuple[str, ...]:
    """The reader's words, as the marker looks for them.

    Split on whitespace and nothing cleverer. The index tokenises its
    own way and this does not pretend to match it - what is marked is
    what was typed.
    """
    return tuple(question.split())


__all__ = ["Passage", "marked_snippet", "passage_of", "terms_of"]
