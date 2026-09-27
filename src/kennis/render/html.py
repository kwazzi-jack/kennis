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

from collections.abc import Callable, Sequence
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


def to_html(markdown: str, *, load_remote_images: bool = False) -> str:
    """`markdown` as HTML, safe to place in a page.

    `load_remote_images` is off by default and is a per-request
    decision rather than a setting, because the reader consenting to
    tell a publisher about one paper has not consented about the next.
    """
    parser = _parser(load_remote_images=load_remote_images)
    return str(parser.render(markdown))


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


__all__ = ["IMAGE_BLOCKED", "IMAGE_MISSING", "to_html"]
