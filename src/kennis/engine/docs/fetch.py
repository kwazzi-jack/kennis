"""One rendered documentation page, as markdown.

The main container is selected rather than the whole page taken, because a
documentation page is mostly navigation. Failing to find one is not a detail:
it is how a fetch refuses a page that is not documentation. A bot challenge,
a login wall and a soft 404 are all served as HTTP 200 with a well-formed
HTML body, so the status code is no evidence at all - see
`design/concerns.md`, entry 34.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urljoin

import httpx

from kennis.engine.errors import SourceUnreadable

_USER_AGENT: Final = "kennis-docs-fetch"
_REQUEST_TIMEOUT_SECONDS: Final = 30

# The rendered main-content container, in preference order. Sphinx themes
# differ on the element and agree on role="main": furo and pydata render
# `<article role="main">`, the classic Read the Docs theme a `<div>`.
_CONTENT_SELECTORS: Final = ('[role="main"]', "div.document", "article")

# Chrome inside the container that carries no prose: the per-heading anchor
# marks, sidebars, breadcrumb and footer navigation, scripts.
_CHROME_SELECTORS: Final = (
    "a.headerlink",
    ".headerlinks",
    ".sphinxsidebar",
    ".related",
    ".footer",
    "script",
    "style",
)


def fetch_page(client: httpx.Client, page_url: str) -> str:
    """The markdown of one page, or a refusal saying why there is none."""
    try:
        response = client.get(page_url, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise SourceUnreadable(f"could not fetch '{page_url}': {error}") from error
    return convert_page(response.text, page_url)


def convert_page(html: str, page_url: str) -> str:
    """A rendered documentation page to markdown holding just its prose.

    Raises `SourceUnreadable` when the document has no main container, which
    is the only available evidence that what came back is not a page of the
    documentation that was asked for.
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    main = None
    for selector in _CONTENT_SELECTORS:
        main = soup.select_one(selector)
        if main is not None:
            break
    if main is None:
        raise SourceUnreadable(
            f"'{page_url}' has no documentation in it: no main-content container"
        )

    for selector in _CHROME_SELECTORS:
        for node in main.select(selector):
            node.decompose()

    # The markdown leaves the site it came from, so a relative reference in it
    # would point at nothing.
    for anchor in main.select("a[href]"):
        anchor["href"] = urljoin(page_url, str(anchor["href"]))
    for image in main.select("img[src]"):
        image["src"] = urljoin(page_url, str(image["src"]))

    markdown = markdownify(
        str(main),
        heading_style="ATX",
        # Identifiers are the point of these pages. Escaping would turn
        # `input_ms` into `input\_ms`, putting a backslash inside the very
        # tokens BM25 will match on.
        escape_underscores=False,
        escape_asterisks=False,
        escape_misc=False,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
