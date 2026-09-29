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

# The same default `render/words.py::snippet_of` uses, so the two
# front ends cut at about the same place even though one counts
# source characters and the other counts characters the reader sees.
_SNIPPET_CHARACTERS: Final = 280

# Below this a term matches most of the page. Two characters is not
# a judgement about which words are worth marking - it is the point
# at which the mark stops carrying information.
_SHORTEST_TERM: Final = 2

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


@dataclass(frozen=True, slots=True)
class _Run:
    """A piece of the snippet: either text to escape, or a tag to emit.

    Kept apart so truncation can count only what the reader sees and
    marking can touch only what the reader reads.
    """

    text: str
    tag: str | None = None


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
    pattern = _pattern(terms)
    return "".join(_rendered(runs, pattern))


def _tokens(chunk: str) -> list[Token]:
    # A parser of its own rather than `render/html.py`'s: this one
    # wants no fences, no images and no tables, because none of them
    # can be shown in four lines of prose.
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
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
    for token in tokens:
        if token.type == "heading_open":
            heading = True
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


def _pattern(terms: Sequence[str]) -> re.Pattern[str] | None:
    """One expression matching any term, whole and regardless of case.

    `re.escape`, because these are a person's words and a query of
    `.*` must match those two characters rather than everything.
    """
    wanted = sorted(
        {term for term in terms if len(term) >= _SHORTEST_TERM},
        key=len,
        reverse=True,
    )
    if not wanted:
        return None
    joined = "|".join(re.escape(term) for term in wanted)
    # `\b` alone fails on a term ending in a non-word character, so
    # the boundary is asserted by lookaround on word characters.
    return re.compile(rf"(?<!\w)(?:{joined})(?!\w)", re.IGNORECASE)


def _rendered(runs: Sequence[_Run], pattern: re.Pattern[str] | None) -> Iterator[str]:
    for run in runs:
        if run.tag is not None:
            yield run.tag
        elif pattern is None:
            yield escape(run.text)
        else:
            yield _marked(run.text, pattern)


def _marked(text: str, pattern: re.Pattern[str]) -> str:
    """Escape the text and wrap each match, keeping the corpus's spelling.

    The replacement uses what was matched rather than what was
    searched for, so "ASTRONOMY" in the document stays "ASTRONOMY"
    when the query said "astronomy". The text kennis quotes is not
    kennis's to re-spell.
    """
    out: list[str] = []
    last = 0
    for found in pattern.finditer(text):
        out.append(escape(text[last : found.start()]))
        out.append(f"<mark>{escape(found.group(0))}</mark>")
        last = found.end()
    out.append(escape(text[last:]))
    return "".join(out)


def terms_of(question: str) -> tuple[str, ...]:
    """The reader's words, as the marker looks for them.

    Split on whitespace and nothing cleverer. The index tokenises its
    own way and this does not pretend to match it - what is marked is
    what was typed.
    """
    return tuple(question.split())


__all__ = ["marked_snippet", "terms_of"]
