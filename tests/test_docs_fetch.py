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
