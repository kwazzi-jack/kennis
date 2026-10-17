"""A corpus document as HTML.

The third rendering of the same text. `render/markdown.py` splits a
body into the blocks a terminal styles differently; this converts it
for a browser. Both are in `render/` because neither is an interface
library - markdown-it is a converter - and the layering allows the
renderer to be shared by any front end that wants it.

Three rules here come from measuring the corpus rather than from
taste, and each would be easy to remove as an over-complication.

**Maths is protected before markdown sees it.** `$x*y*z$` renders as
`$x<em>y</em>z$` through plain markdown-it, because `*y*` is emphasis
before it is TeX. One paper in the corpus carries 343 inline maths
spans, so without `dollarmath` most of that document is corrupted.

**Display maths is also written on one line.** A converted paper puts
equations in table cells, where only inline rules run, so it writes
`$$...$$` inline rather than as a block. Without `double_inline` the
inline rule matches the inner pair and the outer dollars survive as
text: 104 of them in one paper, 13 of 55 documents affected. With it
on, `mdit_py_plugins` renders that token as a `<div>`, which inside a
`<p>` is nesting a browser escapes by closing the paragraph early. So
kennis renders all four maths tokens itself, and the inline forms are
spans.

**A local figure reference is dangling.** Converted PDFs reference
`images/<sha>.jpg` and the conversion keeps no image files - concern
#134. An `<img>` pointing at nothing renders as a broken icon, which
says "this interface is faulty" rather than "this document lost its
figures". A placeholder says the true thing.

**A remote figure is an outbound request the user did not make.**
Rendering an arXiv paper would tell arxiv.org which paper is being
read and when. rules.md 4.5 says sending a document to a third party
is never a default; fetching on their behalf is the same shape, so
remote images are blocked, the host is named, and loading them is a
choice.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final
from urllib.parse import urlparse

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererProtocol
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from mdit_py_plugins.dollarmath import dollarmath_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

# What stands in for an image that is not shown. Two different facts,
# so two different sentences: one is a file the conversion lost and
# the other is a fetch that was declined on the reader's behalf.
IMAGE_MISSING: Final = "figure not kept by the conversion"
IMAGE_BLOCKED: Final = "figure not loaded from"

_REMOTE_SCHEMES: Final = frozenset({"http", "https"})

# markdown-it hands a render rule five positional arguments and wants a
# string back. Written out rather than left as `Any`, because the whole
# point of a rule here is that it is *ours* - the two image decisions
# live inside one - and an untyped callback is where a wrong argument
# order survives review.
type RenderRule = Callable[
    [RendererProtocol, Sequence[Token], int, OptionsDict, EnvType], str
]


@dataclass(frozen=True, slots=True)
class MarkedRange:
    """A range of the source to mark, and the anchor to give it.

    `start` and `end` are character offsets into the same string the
    renderer is handed, which is what `Chunk.char_start` and
    `char_end` already are. The anchor is the fragment a link points
    at, composed by the caller rather than here: `render/` is told
    which passage to mark and does not decide what a chunk is called.
    """

    start: int
    end: int
    anchor: str


def to_html(
    markdown: str,
    *,
    load_remote_images: bool = False,
    marked: MarkedRange | None = None,
    without_title: str | None = None,
    terms: Sequence[str] = (),
    heading_anchors: bool = False,
) -> str:
    """`markdown` as HTML, safe to place in a page.

    `load_remote_images` is off by default and is a per-request
    decision rather than a setting, because the reader consenting to
    tell a publisher about one paper has not consented about the next.

    `marked` wraps the blocks a character range covers, so a reader
    arriving from a search hit lands on the passage rather than at the
    top of a nineteen-page paper. Omitted, the output is byte for byte
    what it was before marking existed.

    `without_title` drops a leading heading that only repeats the
    document's own title. 44 of the 45 crawled pages in one corpus
    open with an `# H1` saying what the frontmatter already says, so
    a reader saw the title twice with the provenance between the two
    copies.

    **Dropped from the tokens, never from the text.**
    `Chunk.char_start` and `char_end` address `Document.body`, so
    editing that string before rendering would put every chunk mark
    out by the heading's length. Concern #353.

    `terms` are the reader's own words, marked on the text the corpus
    holds and never inside code or maths, by the rule a snippet uses.

    `heading_anchors` gives each heading the id `headings_of` names, for
    a page that offers an outline. Off by default, because a results
    page draws several passages and the same id twice is not HTML.
    """
    parser = _parser(load_remote_images=load_remote_images)
    pattern = query_pattern(terms)
    if (
        marked is None
        and without_title is None
        and pattern is None
        and not heading_anchors
    ):
        return str(parser.render(markdown))
    tokens = parser.parse(markdown)
    if marked is not None:
        tokens = _wrapped(tokens, markdown, marked)
    if without_title is not None:
        tokens = _without_title(tokens, without_title)
    if pattern is not None:
        _mark_text(tokens, pattern)
    if heading_anchors:
        for token in tokens:
            if token.type in _HEADINGS and token.map is not None:
                token.attrSet("id", _heading_anchor(token.map[0]))
    return str(parser.renderer.render(tokens, parser.options, {}))


@dataclass(frozen=True, slots=True)
class Heading:
    """One heading of a document, for an outline."""

    level: int
    text: str
    anchor: str


def _heading_anchor(line: int) -> str:
    """A heading's id, from the source line it starts on.

    The line rather than a count of headings, so the anchor is the same
    whether or not the leading title heading was dropped from the tokens.
    """
    return f"heading-{line}"


def headings_of(markdown: str, *, without_title: str | None = None) -> list[Heading]:
    """The headings `to_html` draws, in order, with the ids it gives them.

    The text is the heading's source, which is what a reader recognises;
    inline markup in a heading is rare and is shown as written.
    """
    tokens = _parser(load_remote_images=False).parse(markdown)
    if without_title is not None:
        tokens = _without_title(tokens, without_title)
    return [
        Heading(
            level=int(opening.tag.removeprefix("h")),
            text=inline.content.strip(),
            anchor=_heading_anchor(opening.map[0]),
        )
        for opening, inline in pairwise(tokens)
        if opening.type in _HEADINGS and opening.map is not None
    ]


@dataclass(frozen=True, slots=True)
class PassageHtml:
    """A chunk rendered once, parted where the reader's words first occur.

    `lead` is the blocks before the first block holding a mark, and
    `body` the rest; together they are exactly `to_html(markdown,
    terms=...)`. `fits` says whether both could be shown whole with
    nothing to open: short enough, and holding nothing - a table, a code
    block, a display equation - whose height its characters do not say.
    It counts the lead too, since a passage that fits shows its lead; a
    note's title heading alone is no reason to offer an opening.

    `heading` is the section the passage is from, escaped and marked, for
    the card's header; empty when there is no section to name.
    """

    lead: str
    body: str
    fits: bool
    heading: str = ""


# Blocks whose height is not their length in characters.
_TALL: Final = frozenset(
    {"table_open", "fence", "code_block", "math_block", "math_block_label"}
)


def passage_html(
    markdown: str,
    *,
    terms: Sequence[str],
    fits: int,
    section: str | None = None,
    title: str | None = None,
) -> PassageHtml:
    """`markdown` rendered as `to_html` would, in two parts (#454).

    The part is decided after marking, by where a mark was drawn, so a
    term that occurs only in a link's address - which the reader never
    sees - does not move it. With no mark at all everything is `body`:
    a hit found by meaning alone is shown from its start.

    The card's head says the `section` and the document's `title`, so a
    heading opening the passage with either's words is dropped from the
    tokens rather than said twice (#426) - the title regardless of case,
    as `hit_title_parts` compares them. Only the first block and only the
    same words: any other heading is text the reader has not been shown
    elsewhere.
    """
    parser = _parser(load_remote_images=False)
    tokens = parser.parse(markdown)
    if len(tokens) >= 3 and tokens[0].type == "heading_open":
        words = tokens[1].content.strip()
        if (section and words == section.strip()) or (
            title and words.casefold() == title.strip().casefold()
        ):
            tokens = tokens[3:]
    pattern = query_pattern(terms)
    if pattern is not None:
        _mark_text(tokens, pattern)
    starts = [
        at for at, token in enumerate(tokens) if token.level == 0 and token.nesting >= 0
    ]
    first = next(
        (
            start
            for start, end in pairwise([*starts, len(tokens)])
            if any(_holds_a_mark(token) for token in tokens[start:end])
        ),
        0,
    )
    length = sum(len(token.content) for token in tokens if token.type == "inline")
    return PassageHtml(
        lead=str(parser.renderer.render(tokens[:first], parser.options, {})),
        body=str(parser.renderer.render(tokens[first:], parser.options, {})),
        fits=length <= fits and not any(token.type in _TALL for token in tokens),
        heading=(
            ""
            if not section
            else _escaped(section)
            if pattern is None
            else marked_text(section, pattern)
        ),
    )


def _holds_a_mark(token: Token) -> bool:
    """Whether `_mark_text` drew a mark in this token."""
    return any(
        child.type == "html_inline" and "<mark>" in child.content
        for child in token.children or ()
    )


def terms_of(question: str) -> tuple[str, ...]:
    """The reader's words, as the marker looks for them.

    Split on whitespace and nothing cleverer. The index tokenises its
    own way and this does not pretend to match it - what is marked is
    what was typed.
    """
    return tuple(question.split())


# Below this a term matches most of the page. Two characters is not
# a judgement about which words are worth marking - it is the point
# at which the mark stops carrying information.
_SHORTEST_TERM: Final = 2


def query_pattern(terms: Sequence[str]) -> re.Pattern[str] | None:
    """One expression matching any term, whole and regardless of case.

    `re.escape`, because these are a person's words and a query of
    `.*` must match those two characters rather than everything. Nothing
    is stemmed: the index stems and this does not, so "calibration" will
    not mark "calibrate", and prefix-matching to fix that would mark
    "calibrate" inside "recalibrated", a match the search did not make.
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


def marked_text(text: str, pattern: re.Pattern[str]) -> str:
    """Escape the text and wrap each match, keeping the corpus's spelling.

    The replacement uses what was matched rather than what was searched
    for, so "ASTRONOMY" in the document stays "ASTRONOMY" when the query
    said "astronomy". The text kennis quotes is not kennis's to re-spell.
    """
    out: list[str] = []
    last = 0
    for found in pattern.finditer(text):
        out.append(_escaped(text[last : found.start()]))
        out.append(f"<mark>{_escaped(found.group(0))}</mark>")
        last = found.end()
    out.append(_escaped(text[last:]))
    return "".join(out)


def _mark_text(tokens: Sequence[Token], pattern: re.Pattern[str]) -> None:
    """Mark the reader's words on text and inline code, in place.

    **On tokens, never on finished HTML**, where a query of "class"
    would rewrite `class="..."`. A marked token becomes `html_inline`,
    whose content the renderer writes as it is: `html=False` stops the
    parser making such tokens from the corpus's text, not the renderer
    writing one kennis made, and `marked_text` escaped every character.

    Inline code is marked, as the snippet marks it: a search for
    `solve_gains` is a search for the code. Maths is another token
    type and never reached, because a `<mark>` inside TeX is markup
    KaTeX renders or refuses. A fenced block is left alone, because
    its HTML is the highlighter's.
    """
    for token in tokens:
        for child in token.children or ():
            if not pattern.search(child.content):
                continue
            if child.type == "text":
                child.type = "html_inline"
                child.content = marked_text(child.content, pattern)
            elif child.type == "code_inline":
                child.type = "html_inline"
                child.content = f"<code>{marked_text(child.content, pattern)}</code>"


def _words_of(text: str) -> str:
    """`text` as a comparison sees it: case folded, space collapsed."""
    return " ".join(text.split()).casefold()


def _without_title(tokens: list[Token], title: str) -> list[Token]:
    """`tokens` without a leading `# ` heading that repeats `title`.

    Only the first block, and only the same words - regardless of case
    and of runs of space, as a passage's head compares them (#426): the
    reviews of 2026-10-13 found "gain solutions" over "Gain solutions".
    A document whose first heading says something else is
    a document with a heading, and removing it would lose text the
    corpus holds. A `##` is left alone too - a second-level heading
    is structure, not a title.

    Any wrapper `_wrapped` opened is stepped over rather than
    removed, so a mark that began at the title still opens in the
    right place.
    """
    at = 0
    while at < len(tokens) and tokens[at].type not in _HEADINGS:
        if tokens[at].type != "html_block" and not tokens[at].type.endswith("_open"):
            return tokens
        at += 1
    if at + 2 >= len(tokens) or tokens[at].tag != "h1":
        return tokens
    inline = tokens[at + 1]
    if inline.type != "inline" or _words_of(inline.content) != _words_of(title):
        return tokens
    return tokens[:at] + tokens[at + 3 :]


_HEADINGS: Final = frozenset({"heading_open"})


def _wrapped(tokens: list[Token], markdown: str, marked: MarkedRange) -> list[Token]:
    """`tokens` with an element opened before, and closed after, the
    blocks that `marked` covers.

    **Block-granular, and that is the decision.** Measured on the
    corpus held: 510 of 524 chunks begin and end exactly on a
    top-level block boundary. The 14 that do not are prose paragraphs
    longer than `ChunkParameters.size`, which the packer is allowed to
    bisect; for those this marks the containing paragraph, which shows
    more than the chunk and never less. Marking the exact characters
    would mean mapping offsets through markdown-it's inline tokens,
    which do not carry reliable source positions.

    One element around the whole run rather than one per block,
    because a chunk is one passage: marking each paragraph separately
    would read as three matches where the index recorded one.
    """
    offsets = _line_offsets(markdown)
    # `-1` because an offset that falls inside a line belongs to that
    # line, and `bisect_right` returns the line after it.
    first_line = max(0, bisect_right(offsets, marked.start) - 1)
    # `end` is exclusive and, for a block-aligned range, is the offset
    # of the line after the block - which is the exclusive end of the
    # line range too.
    last_line = bisect_left(offsets, marked.end)

    covered = [
        position
        for position, token in enumerate(tokens)
        if token.level == 0
        and token.nesting != -1
        and token.map is not None
        and token.map[0] < last_line
        and token.map[1] > first_line
    ]
    if not covered:
        # A range that reaches no block. The staleness guard is what
        # should prevent this; rendering the document unmarked is what
        # happens if it ever does not, and it is the harmless outcome.
        return tokens

    opening = Token("html_block", "", 0)
    opening.content = f'<div class="chunk" id="{_escaped(marked.anchor)}">\n'
    closing = Token("html_block", "", 0)
    closing.content = "</div>\n"

    # After the *closing* token of the last covered block, not after
    # the opening one: a container's opening token is what `covered`
    # holds, and its children and closer follow it.
    end = _closes_at(tokens, covered[-1])
    return [
        *tokens[: covered[0]],
        opening,
        *tokens[covered[0] : end],
        closing,
        *tokens[end:],
    ]


def _closes_at(tokens: list[Token], position: int) -> int:
    """One past the token that closes the block opening at `position`.

    A paragraph is `paragraph_open`, `inline`, `paragraph_close`; a
    table is deeper. Walking the nesting counter rather than assuming
    a depth is what makes this work for both.
    """
    if tokens[position].nesting != 1:
        return position + 1
    depth = 0
    for index in range(position, len(tokens)):
        depth += tokens[index].nesting
        if depth == 0:
            return index + 1
    return len(tokens)


def _line_offsets(text: str) -> list[int]:
    """The character offset each line starts at.

    The same walk `rag/chunking.py::_blocks` does in the other
    direction: it turns markdown-it's line numbers into offsets to
    record a chunk, and this turns them back to find it again.
    """
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _parser(*, load_remote_images: bool) -> MarkdownIt:
    """A parser configured for corpus text.

    `html=False` is the important argument and not a default worth
    relying on implicitly: a corpus document is text from outside -
    a converter's output, a crawled page - and rendering its raw HTML
    would let a crawled page place a script on a page that is
    authorised to reach this corpus.
    """
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False})
    parser.enable("table")
    parser.use(dollarmath_plugin, double_inline=True)
    parser.add_render_rule("fence", _render_fence)
    for token_type, element, classes in _MATHS_ELEMENTS:
        parser.add_render_rule(token_type, _maths_rule(element, classes))
    parser.add_render_rule(
        "image",
        _image_rule(load_remote_images=load_remote_images),
    )
    parser.add_render_rule("link_open", _render_link_open)
    return parser


# Which element each maths token becomes, and what it is called.
#
# **`display` is the one class both files read.** `static/typeset.js`
# chooses KaTeX's `displayMode` from it, so the rule lives here and the
# script asks rather than holding a second copy of it. `inline` and
# `block` are for CSS, which wants to know the element's flow and not
# how it is typeset.
#
# The inline forms are spans because that is the whole reason the
# double-inline case exists: it appears inside paragraphs and table
# cells, where a block element is nesting the browser undoes.
_MATHS_ELEMENTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("math_inline", "span", "math inline"),
    ("math_inline_double", "span", "math inline display"),
    ("math_block", "div", "math block display"),
    ("math_block_label", "div", "math block display"),
)


# An optional argument with nothing in it, which KaTeX will not read.
#
# MinerU writes `\begin{array}[]{c}`. LaTeX's `array` takes `t`, `b`
# or `c` in that position and an empty one is not valid there either,
# so it is an artefact of the conversion rather than something an
# author wrote. KaTeX reads the `[`, looks for a column alignment and
# fails on the `]`; that put 16 of one paper's 419 expressions on the
# page as red source text.
#
# Measured across the corpus held: 30 occurrences, every one of them
# `\begin{array}[]` and every one empty. No other environment carries
# an option at all.
#
# **Only when it is empty, and only at render time.** A real option
# changes how the environment is set, so dropping one would change
# the maths rather than repair the conversion. And the document on
# disk is untouched: `Chunk.char_start` and `char_end` address
# `Document.body`, so editing that string would move every mark.
_EMPTY_OPTION: Final = re.compile(r"(\\begin\{[A-Za-z*]+\})\[\s*\]")


def _without_empty_options(maths: str) -> str:
    """`maths` with an empty `\\begin{...}[]` option removed."""
    return _EMPTY_OPTION.sub(r"\1", maths)


def _maths_rule(element: str, classes: str) -> RenderRule:
    """The render rule for one maths token type.

    The content is escaped here rather than by the plugin, because
    these rules replace the plugin's own. TeX is full of characters
    that are markup in HTML - `<`, `>`, `&` all appear in ordinary
    expressions - and KaTeX reads `textContent`, which is the
    unescaped text again.
    """

    def render_maths(
        renderer: RendererProtocol,
        tokens: Sequence[Token],
        index: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[index]
        maths = _without_empty_options(token.content)
        drawn = f'<{element} class="{classes}">{_escaped(maths)}</{element}>'
        if token.info:
            # `$$ ... $$ (eq1)` - the label is what the document's own
            # cross-references point at, so dropping it loses the only
            # handle a reader has on the equation.
            drawn += f'<span class="math-label">({_escaped(token.info)})</span>'
        return drawn + "\n" if element == "div" else drawn

    return render_maths


def _render_fence(
    renderer: RendererProtocol,
    tokens: Sequence[Token],
    index: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    """A code block, highlighted only when its language was declared.

    **An unlabelled block is not guessed at.** `render/markdown.py`
    measured guessing against 262 unlabelled fences in a real corpus
    and got MySQL, GDScript, scdoc and Verilog for content that is
    plainly YAML and shell - `guess_lexer` scores against every lexer
    and so always answers, and on that corpus it was always wrong.
    """
    token = tokens[index]
    language = token.info.strip().split()[0] if token.info.strip() else ""
    if not language:
        return f"<pre><code>{_escaped(token.content)}</code></pre>\n"
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        # A language kennis has no lexer for is still a declared
        # language, so it is not silently guessed at either.
        return f"<pre><code>{_escaped(token.content)}</code></pre>\n"
    return str(highlight(token.content, lexer, HtmlFormatter(nowrap=False)))


def _render_link_open(
    renderer: RendererProtocol,
    tokens: Sequence[Token],
    index: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    """A link out of kennis opens a new tab that cannot reach back.

    Followed in place, it replaced the window with the outside site. The
    server's `Referrer-Policy: no-referrer` already keeps the site from
    learning which document linked to it (#433); `noreferrer` says so on
    the link as well. A link within the document is left as it was.
    """
    token = tokens[index]
    if urlparse(str(token.attrGet("href") or "")).scheme in _REMOTE_SCHEMES:
        token.attrSet("target", "_blank")
        token.attrSet("rel", "noopener noreferrer")
    # Composed here rather than by `renderToken`, which the renderer's
    # protocol does not declare; the href is already normalised by the
    # parser, and every value is escaped as the image's are.
    attributes = "".join(
        f' {name}="{_escaped(str(value))}"' for name, value in token.attrs.items()
    )
    return f"<a{attributes}>"


def _image_rule(*, load_remote_images: bool) -> RenderRule:
    """The render rule for `![alt](src)`, per the two rules above."""

    def render_image(
        renderer: RendererProtocol,
        tokens: Sequence[Token],
        index: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[index]
        # `attrGet` is typed as returning a number too, because an
        # attribute can be one. A `src` cannot, and coercing is
        # honest where asserting the type would be a claim about
        # someone else's parser.
        source = str(token.attrGet("src") or "")
        alt = token.content
        parsed = urlparse(source)
        host = parsed.netloc
        if parsed.scheme in _REMOTE_SCHEMES:
            if not load_remote_images:
                return _placeholder(f"{IMAGE_BLOCKED} {host}", alt)
            return f'<img src="{_escaped(source)}" alt="{_escaped(alt)}">'
        # Every non-remote reference is treated as missing. Not a
        # guess: the corpus keeps no image files at all, so there is
        # no path that could resolve. When conversion starts keeping
        # them (concern #134) this becomes a real lookup, and until
        # then pretending to look would be theatre.
        return _placeholder(IMAGE_MISSING, alt)

    return render_image


def _placeholder(reason: str, alt: str) -> str:
    """What stands where an image is not shown.

    The alt text is kept when there is one, because a converted paper
    writes "Refer to caption" there and that is more than nothing.
    """
    described = f' <span class="role-muted">{_escaped(alt)}</span>' if alt else ""
    return f'<p class="figure-placeholder">[{_escaped(reason)}]{described}</p>\n'


def _escaped(text: str) -> str:
    """HTML-escaped, including quotes, since this reaches attributes."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = [
    "IMAGE_BLOCKED",
    "IMAGE_MISSING",
    "Heading",
    "MarkedRange",
    "PassageHtml",
    "headings_of",
    "marked_text",
    "passage_html",
    "query_pattern",
    "terms_of",
    "to_html",
]
