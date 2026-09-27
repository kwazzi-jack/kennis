"""Markdown to HTML, and the three things a real corpus turns out to need.

Measured on the three papers actually held, not assumed:

- **Maths must be protected before markdown sees it.** `$x*y*z$`
  renders as `$x<em>y</em>z$` through plain markdown-it, because `*y*`
  is emphasis before it is TeX. One paper carries 343 inline maths
  spans, so this is most of that document.
- **A local figure reference is dangling.** Converted PDFs reference
  `images/<sha>.jpg` and the conversion kept no image files (concern
  #134), so an honest renderer says a figure was here rather than
  emitting a broken `<img>`.
- **A remote figure is an outbound request the user did not make.**
  Rendering an arXiv paper would tell arxiv.org which paper is being
  read. kennis's rules say sending a document to a third party is
  never a default; this is the same shape, so it is blocked and
  offered rather than fetched.
"""

from __future__ import annotations

from kennis.render.html import IMAGE_BLOCKED, IMAGE_MISSING, to_html

# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------


def test_markdown_does_not_eat_the_maths():
    """The measurement that made `dollarmath` a requirement rather than
    a nicety: without it the asterisks become emphasis."""
    rendered = to_html("mass $x*y*z$ here")

    assert "<em>" not in rendered
    assert "x*y*z" in rendered


def test_maths_is_marked_for_the_browser_to_typeset():
    rendered = to_html(r"the value $2\times 10^{-5}$ holds")

    assert 'class="math inline"' in rendered
    assert r"2\times 10^{-5}" in rendered


def test_a_displayed_equation_is_distinguished_from_an_inline_one():
    """They are typeset differently, so they cannot share a class."""
    rendered = to_html("$$\nE = mc^2\n$$")

    assert "math block" in rendered


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def test_a_dangling_local_figure_says_so_rather_than_breaking():
    """Concern #134 made visible instead of ugly. Four of these are in
    one paper in the corpus right now."""
    rendered = to_html("![](images/abc123.jpg)")

    assert "<img" not in rendered
    assert IMAGE_MISSING in rendered


def test_a_remote_figure_is_not_fetched_and_names_its_host():
    """Reading a paper must not tell a third party that it is being
    read. The host is named so the choice to load it is informed."""
    rendered = to_html(
        "![Refer to caption](https://arxiv.org/html/2409.19750v1/Fig1.png)"
    )

    assert "<img" not in rendered
    assert IMAGE_BLOCKED in rendered
    assert "arxiv.org" in rendered


def test_a_remote_figure_is_shown_when_it_is_asked_for():
    """The other side of the block, so the test above cannot pass by
    refusing every image unconditionally."""
    rendered = to_html(
        "![Refer to caption](https://arxiv.org/html/2409.19750v1/Fig1.png)",
        load_remote_images=True,
    )

    assert "<img" in rendered
    assert "https://arxiv.org/html/2409.19750v1/Fig1.png" in rendered


def test_asking_for_remote_images_does_not_resurrect_a_missing_local_one():
    """Two different problems. Consenting to a network fetch says
    nothing about a file the conversion threw away."""
    rendered = to_html("![](images/abc123.jpg)", load_remote_images=True)

    assert "<img" not in rendered
    assert IMAGE_MISSING in rendered


# ---------------------------------------------------------------------------
# The ordinary things
# ---------------------------------------------------------------------------


def test_a_table_becomes_a_table():
    """172 rows of one are in the corpus; commonmark alone does not do
    this."""
    rendered = to_html("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in rendered
    assert "<td>1</td>" in rendered


def test_a_fenced_block_is_highlighted_by_its_declared_language():
    rendered = to_html("```python\nvalue = 1\n```")

    assert "highlight" in rendered
    assert "value" in rendered


def test_an_unlabelled_fence_is_not_guessed_at():
    """`render/markdown.py` measured guessing against 262 unlabelled
    fences and got MySQL, GDScript and Verilog for plain YAML and
    shell - not one usable answer. The same rule holds here: an
    unlabelled block is shown as code and not coloured as a language
    it is not."""
    rendered = to_html("```\nkey: value\n```")

    # `highlight`, not `language-`. Pygments emits `class="highlight"`
    # and never `language-`, so asserting the absence of `language-`
    # would pass whether or not the block had been guessed at - which
    # is what it did until this comment was written.
    assert "highlight" not in rendered
    assert "<pre><code>" in rendered
    assert "key: value" in rendered


def test_raw_html_in_a_document_is_not_passed_through():
    """A corpus document is text from outside - a converter's output, a
    crawled page. Rendering its HTML would let a crawled page put a
    script on a page that is authorised to reach this corpus."""
    rendered = to_html("<script>alert(1)</script>\n\nplain text")

    assert "<script>" not in rendered
    assert "plain text" in rendered
