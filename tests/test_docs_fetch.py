"""Turning one rendered documentation page into markdown.

The container is selected rather than the whole page taken, because a doc
site's body is mostly navigation. Failing to find one is how a fetch refuses
a page that is not documentation at all - a bot challenge is served as HTTP
200 with an HTML body, so the status says nothing.
"""

from __future__ import annotations

import pytest

from kennis.engine.docs.fetch import convert_page
from kennis.engine.errors import SourceUnreadable

PAGE_URL = "https://example.org/en/latest/guide/start.html"

FURO = """<html><body>
<div class="sphinxsidebar">Navigation</div>
<article role="main">
  <h1>Getting started<a class="headerlink" href="#top">P</a></h1>
  <p>Set <code>input_ms</code> to the measurement set.</p>
  <p>See <a href="../api/reference.html">the reference</a>.</p>
  <img src="../_images/diagram.png" alt="diagram"/>
  <script>tracker()</script>
</article>
<div class="footer">Copyright</div>
</body></html>
"""

CLASSIC_RTD = """<html><body>
<div role="main"><h1>Classic</h1><p>Body.</p></div>
</body></html>
"""

BARE_ARTICLE = "<html><body><article><h1>Bare</h1><p>Body.</p></article></body></html>"

CHALLENGE = """<html><body>
<h1>Just a moment...</h1>
<p>Checking your browser before accessing the site.</p>
</body></html>
"""


def test_the_main_container_is_what_is_converted():
    markdown = convert_page(FURO, PAGE_URL)

    assert "Getting started" in markdown
    assert "Navigation" not in markdown
    assert "Copyright" not in markdown
    assert "tracker()" not in markdown


def test_heading_anchors_are_dropped():
    assert "headerlink" not in convert_page(FURO, PAGE_URL)
    assert "Getting startedP" not in convert_page(FURO, PAGE_URL)


def test_identifiers_are_not_escaped():
    """Escaping would put a backslash inside the very tokens BM25 matches on,
    turning `input_ms` into `input\\_ms`."""
    assert "input_ms" in convert_page(FURO, PAGE_URL)
    assert "input\\_ms" not in convert_page(FURO, PAGE_URL)


def test_links_and_images_are_resolved_against_the_page():
    markdown = convert_page(FURO, PAGE_URL)

    assert "https://example.org/en/latest/api/reference.html" in markdown
    assert "https://example.org/en/latest/_images/diagram.png" in markdown


@pytest.mark.parametrize(
    ("html", "expected"),
    [(CLASSIC_RTD, "Classic"), (BARE_ARTICLE, "Bare")],
)
def test_the_container_selectors_are_tried_in_order(html: str, expected: str):
    """Sphinx themes differ on the element and agree on role=main, so that is
    tried first; a theme offering neither still usually has an `article`."""
    assert expected in convert_page(html, PAGE_URL)


def test_a_page_with_no_documentation_container_is_refused():
    """The check concern #34 asks for. A challenge page has a perfectly good
    HTML body and no documentation in it."""
    with pytest.raises(SourceUnreadable):
        convert_page(CHALLENGE, PAGE_URL)


# Written by hand in the shapes the themes render (Brian's pydantic add,
# 2026-10-16): Astro Starlight puts the prose in `.sl-markdown-content`, the
# title in a header outside it, and code annotations in pop-ups with the
# same class; its pages can hold cards that are `<article role="listitem">`.
STARLIGHT = """<html><body>
<div class="annotation-popover-content sl-markdown-content">Stray note.</div>
<nav class="sidebar-content">Get Started Concepts API</nav>
<main data-pagefind-body>
  <div class="content-panel"><h1 id="_top">Installation</h1></div>
  <div class="content-panel">
    <div class="sl-markdown-content">
      <p>Install with <code>uv add pydantic</code>.</p>
      <article class="support-area" role="listitem"><h3>Triage</h3></article>
      <div class="annotation-popover-content sl-markdown-content">A note.</div>
    </div>
  </div>
</main>
</body></html>
"""

# MkDocs Material: `<main>` holds both sidebars as well as the article.
MATERIAL = """<html><body>
<main class="md-main"><div class="md-main__inner">
  <div class="md-sidebar">Navigation</div>
  <div class="md-content"><article class="md-content__inner md-typeset">
    <h1>Validators</h1><p>Field validators run after parsing.</p>
  </article></div>
</div></main>
</body></html>
"""

# A page with only `<main>`, whose cards are articles.
MAIN_WITH_CARDS = """<html><body>
<main><h1>Support</h1><p>Ways to get help.</p>
<article role="listitem"><h3>Triage</h3><p>Incidents.</p></article>
<article role="listitem"><h3>Reviews</h3><p>Design reviews.</p></article>
</main></body></html>
"""


def test_a_starlight_page_is_its_prose_under_its_own_title():
    markdown = convert_page(STARLIGHT, PAGE_URL)

    assert markdown.startswith("# Installation\n")
    assert "uv add pydantic" in markdown
    assert "Get Started Concepts API" not in markdown
    assert "Stray note." not in markdown


def test_a_material_page_is_its_article_not_its_navigation():
    markdown = convert_page(MATERIAL, PAGE_URL)

    assert "Field validators run after parsing." in markdown
    assert "Navigation" not in markdown


def test_a_card_is_not_taken_for_the_page():
    """pydantic's enterprise-support page was stored as its first card,
    "Production incident triage", because a card is an `article`."""
    markdown = convert_page(MAIN_WITH_CARDS, PAGE_URL)

    assert "Ways to get help." in markdown
    assert "Reviews" in markdown


def test_a_title_outside_the_container_is_not_taken_when_there_are_two():
    two = STARLIGHT.replace('<h1 id="_top">Installation</h1>', "<h1>A</h1><h1>B</h1>")

    markdown = convert_page(two, PAGE_URL)

    assert not markdown.startswith("# ")


def test_a_page_of_nothing_but_cards_is_refused_rather_than_taken_as_one():
    cards = (
        '<html><body><article role="listitem"><h3>Triage</h3></article>'
        '<article role="listitem"><h3>Reviews</h3></article></body></html>'
    )

    with pytest.raises(SourceUnreadable):
        convert_page(cards, PAGE_URL)


def test_a_refusal_does_not_repeat_the_page_it_is_about():
    """Every line already names its page, so eight refusals read as eight
    reasons and could not be grouped under the one they share."""
    with pytest.raises(SourceUnreadable) as refused:
        convert_page(CHALLENGE, PAGE_URL)

    assert PAGE_URL not in str(refused.value)
    assert "no main-content container" in str(refused.value)
