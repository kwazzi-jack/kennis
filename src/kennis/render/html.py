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

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
    """
    parser = _parser(load_remote_images=load_remote_images)
    if marked is None and without_title is None:
        return str(parser.render(markdown))
    tokens = parser.parse(markdown)
    if marked is not None:
        tokens = _wrapped(tokens, markdown, marked)
    if without_title is not None:
        tokens = _without_title(tokens, without_title)
    return str(parser.renderer.render(tokens, parser.options, {}))


def _without_title(tokens: list[Token], title: str) -> list[Token]:
    """`tokens` without a leading `# ` heading that repeats `title`.

    Only the first block, and only an exact match once both are
    stripped: a document whose first heading says something else is
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
    if inline.type != "inline" or inline.content.strip() != title.strip():
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
    parser.use(dollarmath_plugin)
    parser.add_render_rule("fence", _render_fence)
    parser.add_render_rule(
        "image",
        _image_rule(load_remote_images=load_remote_images),
    )
    return parser


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


__all__ = ["IMAGE_BLOCKED", "IMAGE_MISSING", "MarkedRange", "to_html"]
