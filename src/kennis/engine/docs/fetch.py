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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urljoin

import httpx

from kennis.engine.docs.http import get_within, origin_of
from kennis.engine.errors import SourceUnreadable

if TYPE_CHECKING:
    from bs4 import Tag

_REQUEST_TIMEOUT_SECONDS: Final = 30

# The rendered main-content container, in preference order. Sphinx themes
# differ on the element and agree on role="main": furo and pydata render
# `<article role="main">`, the classic Read the Docs theme a `<div>`.
# Astro Starlight (pydantic's docs) has neither: its prose is in
# `.sl-markdown-content`, a class its code annotations' pop-ups share. MkDocs
# Material's `<main>` holds the navigation too, so its article comes before
# `main`; and a bare `article` comes last and never as a list item, because a
# page of cards is a page of articles - pydantic's support page was stored as
# its first card.
_CONTENT_SELECTORS: Final = (
    ".sl-markdown-content:not(.annotation-popover-content)",
    '[role="main"]',
    "div.document",
    "article.md-content__inner",
    "main",
    'article:not([role="listitem"])',
)

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


@dataclass(frozen=True, slots=True)
class Validators:
    """What a site sent to identify one copy of a page: its `ETag` and
    `Last-Modified` headers, verbatim, either of which may be absent."""

    etag: str | None = None
    last_modified: str | None = None

    def conditions(self) -> dict[str, str]:
        """The headers that ask the site for the page only if it changed."""
        asked: dict[str, str] = {}
        if self.etag is not None:
            asked["If-None-Match"] = self.etag
        if self.last_modified is not None:
            asked["If-Modified-Since"] = self.last_modified
        return asked


@dataclass(frozen=True, slots=True)
class FetchedPage:
    markdown: str
    validators: Validators


def fetch_page(client: httpx.Client, page_url: str) -> FetchedPage:
    """One page and the validators its site sent, or a refusal saying why
    there is none."""
    fetched = _fetched(client, page_url, Validators())
    if fetched is None:
        # Nothing was asked conditionally, so a 304 is no page at all.
        raise SourceUnreadable("could not fetch the page: the site sent no page")
    return fetched


def fetch_page_if_changed(
    client: httpx.Client, page_url: str, held: Validators
) -> FetchedPage | None:
    """As `fetch_page`, or None when the site answers that the copy `held`
    identifies is still current. A site that ignores the conditions sends
    the page in full, and the caller compares the text instead."""
    return _fetched(client, page_url, held)


def _fetched(
    client: httpx.Client, page_url: str, held: Validators
) -> FetchedPage | None:
    conditions = held.conditions()
    try:
        response = get_within(
            client, page_url, origin=origin_of(page_url), headers=conditions or None
        )
        if conditions and response.status_code == httpx.codes.NOT_MODIFIED:
            return None
        response.raise_for_status()
    except httpx.HTTPError as error:
        # The page is named by every line that reports this; saying it
        # again made each refusal a different sentence (#473).
        raise SourceUnreadable(f"could not fetch the page: {error}") from error
    return FetchedPage(
        markdown=convert_page(response.text, page_url),
        validators=Validators(
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        ),
    )


# Where a site writes a code block's language: Starlight and MkDocs as a
# class on the <code> (`language-python`), Sphinx as a class two levels
# above the <pre> (`highlight-yaml`), Expressive Code as `data-language`.
_LANGUAGE_CLASS: Final = re.compile(r"(?:language|highlight)-([A-Za-z0-9_+.#-]+)")
# How many elements above the <pre> may carry the mark. Sphinx needs two;
# further up, a class says something about the page, not about the block.
_LANGUAGE_REACH: Final = 3


def marked_language(pre: Tag) -> str | None:
    """The language the site marked on one code block, as Pygments names
    it, or None (#354, #491).

    Read from the site's own markup and never guessed from the code: a
    guess named the right language for 16% of 3,972 blocks whose language
    was known. A name Pygments has no lexer for is dropped - Sphinx marks a
    terminal session `highlight-pytest` - because Pygments is what colours
    the block, and a name nothing reads is a label without a use.
    """
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    looked_at: list[Tag] = [pre]
    code = pre.find("code")
    if code is not None:
        looked_at.append(code)
    looked_at += list(pre.parents)[:_LANGUAGE_REACH]
    for element in looked_at:
        named = element.get("data-language")
        candidates = [named] if isinstance(named, str) else []
        candidates += [
            found.group(1)
            for found in map(
                _LANGUAGE_CLASS.fullmatch, element.get_attribute_list("class")
            )
            if found is not None
        ]
        for candidate in candidates:
            try:
                get_lexer_by_name(candidate.lower())
            except ClassNotFound:
                continue
            return candidate.lower()
    return None


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
            "the page has no documentation in it: no main-content container"
        )

    for selector in _CHROME_SELECTORS:
        for node in main.select(selector):
            node.decompose()

    # A theme that draws the title in a header outside the prose (Starlight)
    # would leave the page titled by its path. Only one heading of the page's
    # own is unambiguous.
    if main.find("h1") is None:
        titles = soup.find_all("h1")
        if len(titles) == 1:
            main.insert(0, titles[0].extract())

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
        code_language_callback=marked_language,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
