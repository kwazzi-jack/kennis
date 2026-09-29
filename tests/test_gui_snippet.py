"""A snippet that reads, code colour that shows, and the query marked.

Three pieces of one idea: work kennis already does and then throws
away at the medium boundary.

**Markdown in a snippet** was concern #336, open because fixing it
decides something about #297 rather than about styling. The decision:
the window renders, `rendered_hit` goes on handing `cli` and `mcp`
the same string it always did, and #297's claim narrows from "the
same bytes" to "the same bytes for the headline and the detail, the
same source text for the body". The narrowing is asserted here, not
merely described.

**Code highlighting** already runs - pygments, on every fenced block
with a declared language - and emitted classes no stylesheet had a
rule for. The test that matters collects the classes pygments
actually produces rather than the ones its documentation mentions.

**The mark** must never see a tag. Marking finished HTML for a query
of "class" would rewrite `class="basis"`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui.app import build_app
from kennis.gui.snippet import marked_snippet
from kennis.gui.theme import stylesheet
from kennis.render.html import to_html

TOKEN = "a-test-token"


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(TOKEN), follow_redirects=False)


def admitted(client: TestClient) -> None:
    client.get("/", params={"token": TOKEN})


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def _words(html: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", " ", html).lower())


# ---------------------------------------------------------------------------
# The snippet reads
# ---------------------------------------------------------------------------


def test_a_heading_marker_does_not_reach_the_reader():
    """`## V Inference Methodology` was what the window showed. The
    marker is markdown's, not the corpus's prose."""
    shown = marked_snippet("## V Inference Methodology\n\nTo quantify it.", terms=())

    assert "##" not in shown
    assert "V Inference Methodology" in shown


def test_the_snippet_is_never_one_enormous_heading():
    """The obvious implementation - run the markdown renderer on the
    snippet string - produces exactly this, because `snippet_of`
    collapses the whitespace first and the heading then swallows the
    paragraph after it."""
    shown = marked_snippet("## A Heading\n\nAnd a sentence after it.", terms=())

    assert "<h1" not in shown and "<h2" not in shown
    assert "And a sentence after it" in shown


def test_emphasis_survives_as_emphasis():
    shown = marked_snippet("The *gain* is **large** and `solve()` runs.", terms=())

    assert "<em>gain</em>" in shown
    assert "<strong>large</strong>" in shown
    assert "<code>solve()</code>" in shown


def test_a_citation_keeps_its_text_and_loses_its_url():
    """`[[35](https://example.org/x)]` is a citation. The number is
    what a reader wants; the address is the noise this exists to
    remove, and an anchor in a hit list is an outbound path from a
    page that has none."""
    shown = marked_snippet("As shown [[35](https://example.org/x)] before.", terms=())

    assert "35" in shown
    assert "example.org" not in shown
    assert "<a " not in shown


def test_the_snippet_is_cut_at_a_word_boundary():
    """Cutting mid-word makes a snippet look corrupted rather than
    shortened, and the partial word carries nothing.

    **The limit has to fall inside a word for this to test
    anything.** The first version used words of six characters
    including their space and a limit of 60, so the cut landed
    exactly on a space: dropping the word-boundary logic changed the
    result by one trailing space, which the `rstrip` two lines later
    removed anyway. The injection was inert and the test could not
    have failed. Concern #352.
    """
    words = [f"word{number}" for number in range(400)]
    long_text = " ".join(words)
    limit = 57
    assert long_text[limit] not in " ", "the cut must land inside a word"

    shown = marked_snippet(long_text, terms=(), limit=limit)

    assert len(re.sub(r"<[^>]+>", "", shown)) <= limit + 4
    assert shown.rstrip().endswith("...")
    # Every word shown is a whole word of the source, which is the
    # property - not the absence of one particular fragment.
    held = set(words)
    shown_words = re.sub(r"<[^>]+>", "", shown).removesuffix("...").split()
    assert all(word in held for word in shown_words), shown_words


def test_a_cut_inside_emphasis_still_closes_its_tags():
    """Truncation happens on the runs, before they become tags -
    otherwise the cut lands inside `<em>` and the page carries an
    unclosed element into everything after it."""
    text = "Start here *and then a very long emphasised passage continues*."

    shown = marked_snippet(text, terms=(), limit=30)

    assert shown.count("<em>") == shown.count("</em>")


def test_html_in_the_corpus_is_escaped_not_run():
    """A document may contain anything. The snippet is quoted text
    and must reach the page as text."""
    shown = marked_snippet("A <script>alert(1)</script> tag.", terms=())

    assert "<script>" not in shown
    assert "&lt;script&gt;" in shown


# ---------------------------------------------------------------------------
# The query is marked
# ---------------------------------------------------------------------------


def test_the_query_terms_are_marked():
    shown = marked_snippet(
        "To quantify astronomy we employed benchmarking methods.",
        terms=("astronomy", "benchmarking"),
    )

    assert "<mark>astronomy</mark>" in shown
    assert "<mark>benchmarking</mark>" in shown


def test_marking_is_case_insensitive_and_keeps_the_corpus_spelling():
    """The corpus's capitals are the corpus's. Marking must not
    rewrite the text it marks."""
    shown = marked_snippet("Astronomy and ASTRONOMY.", terms=("astronomy",))

    assert "<mark>Astronomy</mark>" in shown
    assert "<mark>ASTRONOMY</mark>" in shown


def test_marking_is_whole_word():
    """Otherwise a search for "gain" marks the middle of "against",
    which tells the reader their query matched something it did
    not."""
    shown = marked_snippet("Against the gain.", terms=("gain",))

    assert "<mark>gain</mark>" in shown
    assert "A<mark>gain</mark>st" not in shown


def test_a_term_never_reaches_the_markup():
    """The reason marking happens on the text runs rather than on
    finished HTML. A query of "class" or "em" applied to rendered
    output rewrites the tags."""
    shown = marked_snippet("The *emphasis* of a class.", terms=("em", "class"))

    assert "<em>emphasis</em>" in shown
    assert "<mark>class</mark>" in shown
    assert "<m<mark>" not in shown


def test_a_one_character_term_is_not_marked():
    """It would mark most of the page."""
    shown = marked_snippet("A cat sat on a mat.", terms=("a",))

    assert "<mark>" not in shown


def test_a_term_inside_a_code_span_is_still_marked():
    shown = marked_snippet("Call `solve_gains()` first.", terms=("solve_gains",))

    assert "<code>" in shown and "<mark>" in shown


def test_a_regular_expression_in_the_query_is_not_one():
    """The query is a person's words and reaches a regex. `.*` must
    match the characters, not everything."""
    shown = marked_snippet("Nothing to see here.", terms=(".*",))

    assert "<mark>" not in shown


# ---------------------------------------------------------------------------
# What #297 still promises
# ---------------------------------------------------------------------------


def test_the_window_snippet_says_the_same_words_as_the_command_line(
    corpus: Path, client: TestClient
):
    """#297 narrowed rather than lapsed.

    `headline` and `detail` stay byte-identical across front ends,
    which `test_render_hits.py` goes on asserting whole line by whole
    line. `body` becomes the same source text rendered for its
    medium, and this is what that means: every word the window shows
    appears in the command line's snippet, in the same order. Content
    may not drift; punctuation may.
    """
    run = CliRunner()
    body = (
        "## V Inference Methodology\n\n"
        "To quantify the performance of *specialized* models for "
        "astronomy we employed three distinct benchmarking methods "
        "[[35](https://example.org/paper)].\n"
    )
    source = corpus / "note.md"
    source.write_text(f"# Benchmarks\n\n{body}", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    admitted(client)

    printed = run.invoke(main, ["search", "astronomy", "--collection", "notes"])
    page = client.get("/", params={"q": "astronomy", "scope": "notes"})

    from_terminal = _words(printed.output)
    from_window = _words(
        re.search(r'<p class="body">(.*?)</p>', page.text, re.S).group(1)
    )
    assert from_window, page.text
    index = 0
    for word in from_window:
        index = from_terminal.index(word, index)


# ---------------------------------------------------------------------------
# The highlighting shows
# ---------------------------------------------------------------------------

_SAMPLES: dict[str, str] = {
    "python": "class Thing:\n    # a comment\n    def solve(self):\n"
    "        return 'x' * 2\n",
    "bash": 'ls -l /tmp  # a comment\necho "$HOME"\n',
    # YAML earns its place: its lexer emits token types pygments has
    # no short name for, so they arrive as `l-Scalar-Plain` and
    # `p-Indicator` rather than as `l` and `p`.
    "yaml": "key: value\n# a comment\nlist:\n  - 1\n  - two\n",
    "json": '{"key": "value", "number": 2}\n',
    "toml": '[section]\n# a comment\nkey = "value"\nnumber = 2\n',
    "sql": "SELECT name FROM t WHERE id = 1; -- a comment\n",
    "diff": "--- a\n+++ b\n-gone\n+new\n",
}


def _emitted_classes() -> set[str]:
    """Every class pygments puts around visible content.

    Two things the first version of this got wrong, and both would
    have made it pass while missing classes.

    `[a-z]+` misses any class with a digit or a capital - `s1`, `c1`,
    and YAML's `l-Scalar-Plain` - which is most of the interesting
    ones. And a span may carry several classes.

    Whitespace-only spans are excluded: pygments wraps indentation in
    `w`, and a colour for whitespace is not a thing to assert.
    """
    found: set[str] = set()
    for language, code in _SAMPLES.items():
        html = to_html(f"```{language}\n{code}```\n")
        for attribute, content in re.findall(
            r'<span class="([^"]+)">([^<]*)</span>', html
        ):
            if content.strip():
                found.update(attribute.split())
    return found


def _has_a_colour(emitted: str, css: str) -> bool:
    """Whether the stylesheet colours this class, either way it can.

    Two mechanisms, because pygments emits two shapes. A standard
    type arrives as its short name and gets an exact rule. A type
    the lexer invented arrives as its root joined to the rest of its
    path - YAML's `l-Scalar-Plain` - and is covered by a prefix
    selector on the root.

    Checked the way the browser resolves it rather than by looking
    for one spelling, which is what the first version of this did
    and why it reported two classes missing that were not.
    """
    if f".highlight .{emitted} {{" in css:
        return True
    root = emitted.split("-")[0]
    return f'.highlight [class^="{root}-"] {{' in css


def test_pygments_really_does_emit_classes():
    """The premise. If highlighting stopped running, every assertion
    below would pass against an empty set."""
    assert len(_emitted_classes()) > 5


def test_every_class_pygments_emits_has_a_colour():
    """The defect, stated as it was found: highlighting ran on every
    fenced block and the stylesheet had no rule for any class it
    produced, so a document with code rendered one flat colour.

    Collected from real output rather than from pygments'
    documentation, because a mapping written from the documentation
    misses whatever the documentation does not mention.
    """
    css = stylesheet()

    missing = {
        emitted for emitted in _emitted_classes() if not _has_a_colour(emitted, css)
    }

    assert missing == set(), missing


def test_the_code_colours_are_the_roles_and_not_new_ones():
    """`render/theme.py` decides which role wears which of the nine
    names and `gui/theme.py` decides what a name looks like here.
    A pygments mapping that picked its own colours would be a second
    palette deciding the same thing."""
    css = stylesheet()
    highlighting = [line for line in css.splitlines() if ".highlight ." in line]

    assert highlighting
    for rule in highlighting:
        assert "var(--role-" in rule, rule


def test_a_comment_is_not_the_body_colour():
    """`code_comment` is `Role(dim=True)` with no colour, so the
    adapter emitted `inherit` and a comment rendered as prose. Dim is
    a terminal attribute and a browser has none, so the adapter
    translates it - the same argument that made `white` the
    foreground rather than `#FFFFFF`."""
    css = stylesheet()

    assert "--role-code_comment: inherit" not in css


def test_a_heading_keeps_its_boundary_without_adding_characters():
    """Flattening the blocks ran a section title into the paragraph
    after it - "Methodology To quantify the performance" - because
    the `##` that marked the boundary is what this unit removes.

    Bold rather than a separator, because a separator is text the
    corpus does not contain and a snippet is quoted text.
    """
    shown = marked_snippet("## V Inference Methodology\n\nTo quantify it.", terms=())

    assert "<strong>V Inference Methodology</strong>" in shown
    assert "-" not in shown


def test_a_heading_is_not_bold_in_the_words_only(corpus: Path):
    """The weight has to come from the markup rather than from the
    text gaining asterisks, which would be the marker back again
    under another name."""
    shown = marked_snippet("## Heading\n\nAfter.", terms=())

    assert "**" not in shown
    assert "Heading" in shown


def test_a_document_page_does_not_show_its_title_twice(
    corpus: Path, client: TestClient
):
    """`to_html` was tested and its caller was not, so turning the
    feature off in `shown_document` broke nothing - the injection
    that found this changed real behaviour and no test noticed.

    Measured on the corpus that prompted the fix: 44 of 45 crawled
    pages open with an `# H1` repeating their frontmatter title, so
    the reader saw the title, the provenance, and then the title
    again. Concern #353.
    """
    run = CliRunner()
    source = corpus / "page.md"
    source.write_text(
        "# Substitutions and formulas\n\nThe body of the page.\n", encoding="utf-8"
    )
    assert (
        run.invoke(
            main,
            [
                "corpus",
                "add",
                "-n",
                str(source),
                "--title",
                "Substitutions and formulas",
            ],
        ).exit_code
        == 0
    )
    admitted(client)
    held = run.invoke(main, ["corpus", "tree"])
    assert held.exit_code == 0, held.output

    listing = client.get("/collection/notes")
    identifier = re.search(r"/document/notes/([a-z0-9]+)", listing.text)
    assert identifier is not None, listing.text
    page = client.get(f"/document/notes/{identifier.group(1)}")

    assert page.status_code == 200
    assert page.text.count("Substitutions and formulas</h1>") == 1
    assert "The body of the page." in page.text
