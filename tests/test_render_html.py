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

from kennis.engine.rag.chunking import ChunkParameters, chunk_document
from kennis.engine.rag.models import Document as RagDocument
from kennis.render.html import (
    IMAGE_BLOCKED,
    IMAGE_MISSING,
    MarkedRange,
    to_html,
)

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


# ---------------------------------------------------------------------------
# Marking one chunk
# ---------------------------------------------------------------------------
#
# A search hit names a chunk, and the reader should open at it rather
# than at the top of a 19-page paper. `Chunk` already carries
# `char_start` and `char_end`, so the range exists; what this section
# covers is turning a range of the *markdown* into a range of the
# rendered elements.
#
# The marking is block-granular. Measured on the corpus actually held:
# 510 of 524 chunks begin and end exactly on a top-level block
# boundary, and the 14 that do not are prose paragraphs longer than
# `ChunkParameters.size`, which `_pack` is allowed to bisect. For
# those the mark covers the containing paragraph - a superset of the
# chunk, never a subset.

_THREE_BLOCKS = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"


def test_no_range_renders_exactly_as_before():
    """The marking is opt-in. A reader who asked for no chunk gets the
    document byte for byte as it rendered before this existed."""
    assert to_html(_THREE_BLOCKS, marked=None) == to_html(_THREE_BLOCKS)


def test_the_marked_block_carries_the_anchor():
    start = _THREE_BLOCKS.index("Second")
    end = _THREE_BLOCKS.index("Third")

    rendered = to_html(
        _THREE_BLOCKS, marked=MarkedRange(start=start, end=end, anchor="chunk-1")
    )

    assert 'id="chunk-1"' in rendered
    # The anchor opens before the marked paragraph and closes after
    # it, so the marked text falls inside the element that carries it.
    marked = rendered[rendered.index('id="chunk-1"') :]
    assert "Second paragraph." in marked[: marked.index("</div>")]


def test_blocks_outside_the_range_are_not_marked():
    start = _THREE_BLOCKS.index("Second")
    end = _THREE_BLOCKS.index("Third")

    rendered = to_html(
        _THREE_BLOCKS, marked=MarkedRange(start=start, end=end, anchor="chunk-1")
    )

    before, _, rest = rendered.partition('id="chunk-1"')
    inside, _, after = rest.partition("</div>")
    assert "First paragraph." in before
    assert "Third paragraph." in after
    assert "First" not in inside and "Third" not in inside


def test_a_range_over_several_blocks_is_one_mark_and_not_several():
    """One chunk is one passage. Marking each paragraph separately
    would read as three matches where the index recorded one."""
    start = _THREE_BLOCKS.index("First")
    end = len(_THREE_BLOCKS)

    rendered = to_html(
        _THREE_BLOCKS, marked=MarkedRange(start=start, end=end, anchor="chunk-0")
    )

    assert rendered.count('id="chunk-0"') == 1
    assert rendered.count('class="chunk"') == 1


def test_a_range_beginning_mid_block_marks_the_whole_block():
    """The 2.7% case, asserted as a superset rather than avoided.

    `_pack` bisects a prose paragraph longer than `size`, so a chunk
    can begin part-way through one. Marking the containing paragraph
    shows more than the chunk and never less; marking only the exact
    characters would need reliable inline source offsets, which
    markdown-it does not provide."""
    start = _THREE_BLOCKS.index("paragraph", _THREE_BLOCKS.index("Second"))
    end = _THREE_BLOCKS.index("Third")

    rendered = to_html(
        _THREE_BLOCKS, marked=MarkedRange(start=start, end=end, anchor="chunk-1")
    )

    marked = rendered[rendered.index('id="chunk-1"') :]
    inside = marked[: marked.index("</div>")]
    assert "Second paragraph." in inside


def test_marking_does_not_disturb_the_maths():
    """The mark wraps blocks and must not re-parse their contents:
    `dollarmath` protects `$x*y*z$`, and a marked document is still a
    document."""
    source = "before\n\nmass $x*y*z$ here\n\nafter\n"
    start = source.index("mass")
    end = source.index("after")

    rendered = to_html(
        source, marked=MarkedRange(start=start, end=end, anchor="chunk-1")
    )

    assert "<em>" not in rendered
    assert "x*y*z" in rendered


def test_marking_does_not_let_raw_html_through():
    """The wrapper is emitted by kennis; the document's own HTML is
    still refused. A marked document is not a more trusting one."""
    source = "plain\n\n<script>alert(1)</script>\n\nmore\n"
    start = source.index("<script>")
    end = source.index("more")

    rendered = to_html(
        source, marked=MarkedRange(start=start, end=end, anchor="chunk-1")
    )

    assert "<script>" not in rendered
    assert 'id="chunk-1"' in rendered


def test_a_range_past_the_end_of_the_document_marks_nothing():
    """Defensive rather than theoretical: the range comes from an
    index, and an index can be behind the document it describes. The
    staleness guard is the real answer, and this is what happens if it
    ever fails to fire."""
    rendered = to_html(
        _THREE_BLOCKS, marked=MarkedRange(start=10_000, end=20_000, anchor="chunk-9")
    )

    assert 'id="chunk-9"' not in rendered
    assert "First paragraph." in rendered


# ---------------------------------------------------------------------------
# The two sides address the same string
# ---------------------------------------------------------------------------


def test_the_chunker_and_the_reader_address_the_same_text():
    """The load-bearing agreement, asserted rather than assumed.

    The reader renders `Document.body`; the chunker chunks
    `rag.Document.text`, which `rag/loaders.py` fills from `held.body`.
    Were a loader ever to index the file including its frontmatter,
    every offset would be long by the length of that block and the
    mark would sit confidently on the wrong paragraph - wrong by a
    plausible amount, which is the hardest kind to notice.

    Asserting that the marked text *is* the chunk's text checks both
    halves at once: that the offsets mean what the renderer thinks,
    and that the two modules measure from the same origin."""
    body = "\n\n".join(f"Paragraph number {number}." for number in range(12)) + "\n"
    document = RagDocument(
        id="d", collection="notes", text=body, source_path="d.md", metadata={}
    )

    chunks = chunk_document(
        document, collection="notes", parameters=ChunkParameters(size=120, overlap=0)
    )
    assert len(chunks) > 2, "the sample must produce several chunks to be a test"

    chunk = chunks[1]
    rendered = to_html(
        body,
        marked=MarkedRange(
            start=chunk.char_start, end=chunk.char_end, anchor="chunk-1"
        ),
    )
    inside = rendered[rendered.index('id="chunk-1"') :].partition("</div>")[0]

    for sentence in chunk.text.split("\n\n"):
        if sentence.strip():
            assert sentence.strip() in inside


def test_a_leading_heading_that_repeats_the_title_is_dropped():
    """Measured before fixing: 44 of the 45 crawled pages in the
    corpus open with an `# H1` saying exactly what the frontmatter
    title says, so the reader saw the title, then the provenance,
    then the title again.

    The v0.6c sketch recorded this as fixed and it was not; nothing
    tested it. Concern #353.
    """
    shown = to_html("# Substitutions\n\nThe body.", without_title="Substitutions")

    assert "<h1>" not in shown
    assert "<p>The body.</p>" in shown


def test_a_heading_saying_something_else_is_kept():
    """Removing it would lose text the corpus holds."""
    shown = to_html("# Another heading\n\nThe body.", without_title="The title")

    assert "<h1>Another heading</h1>" in shown


def test_a_second_level_heading_is_never_dropped():
    """A `##` is structure rather than a title, even where its words
    happen to match."""
    shown = to_html("## The title\n\nThe body.", without_title="The title")

    assert "<h2>The title</h2>" in shown


def test_dropping_the_title_does_not_move_a_chunk_mark():
    """The reason this happens to the tokens and never to the text.
    `Chunk.char_start` addresses `Document.body`, so editing that
    string before rendering would put every mark out by the
    heading's length - the invariant a whole unit was built on."""
    body = "# The title\n\nFirst paragraph.\n\nSecond paragraph.\n"
    start = body.index("Second paragraph.")
    marked = MarkedRange(start=start, end=start + len("Second paragraph."), anchor="c")

    shown = to_html(body, marked=marked, without_title="The title")

    assert "<h1>" not in shown
    before, _, after = shown.partition('<div class="chunk" id="c">')
    assert "First paragraph." in before
    assert "Second paragraph." in after
