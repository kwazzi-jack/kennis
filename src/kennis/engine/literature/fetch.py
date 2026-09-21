"""Fetching a paper's text from arXiv's LaTeXML renderings.

Two sources emit the same `ltx_*`-classed DOM, so one converter serves both.
arXiv's own native HTML5 rendering is tried first because it is authoritative
and is being backfilled; `ar5iv` is the fallback because its historical
coverage is broader. A paper with neither - typically pre-arXiv-era, or never
preprinted - is reported unavailable.

**Nothing here raises for a paper it cannot get.** The identifier and the
bibliography are already in hand by the time this is called, and those are the
parts that stop the same paper landing twice; a missing body is a smaller loss
than a refused add. `convert_arxiv_html` is the exception, because a caller
handing it a specific document is asking whether *that* document converts.

Only arXiv is reached. A publisher's own PDF is served against a session
established by rendering the article page, so a standalone process cannot
follow the download link even when the paper is readable in a browser - see
`design/concerns.md`, entry 34.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin

import httpx

from kennis.engine.errors import SourceUnreadable

_ARXIV_HTML: Final = "https://arxiv.org/html/{arxiv_id}"
_AR5IV_HTML: Final = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
_SOURCES: Final = (("arxiv-html", _ARXIV_HTML), ("ar5iv", _AR5IV_HTML))

_USER_AGENT: Final = "kennis-literature-fetch"
_REQUEST_TIMEOUT_SECONDS: Final = 30

# The container every LaTeXML-generated page wraps its content in, identical
# on both sources because ar5iv runs the same renderer.
_ARTICLE_SELECTOR: Final = "article.ltx_document"

# Chrome carrying no prose: the banner and report-an-issue furniture either
# site puts around the article.
_CHROME_SELECTORS: Final = (
    ".ltx_page_header",
    ".ltx_page_footer",
    "nav",
    "script",
    "style",
)


@dataclass(frozen=True, slots=True)
class PaperText:
    """A paper's body, and where it came from.

    `source` is `arxiv-html`, `ar5iv`, or `unavailable`, in which case
    `markdown` and `page_url` are both None and `reason` says what the sources
    answered. **The reason is the point of the field**: degrading a failure to
    "no text" is right for a paper arXiv has not rendered and wrong for a
    request arXiv refused, and the caller cannot tell those apart from a None.
    """

    markdown: str | None
    source: str
    page_url: str | None
    reason: str | None = None


def fetch_paper(arxiv_id: str, *, client: httpx.Client | None = None) -> PaperText:
    """The text of one paper, or the answer that there is none.

    `client` is supplied by the caller so a test hands over a transport that
    never touches the network; left out, one is built and closed here.
    """
    owned = client is None
    active = client or httpx.Client(headers={"User-Agent": _USER_AGENT})
    refusals: list[str] = []
    try:
        for source, template in _SOURCES:
            page_url = template.format(arxiv_id=arxiv_id)
            markdown, refusal = _rendering_at(active, page_url)
            if markdown is not None:
                return PaperText(markdown=markdown, source=source, page_url=page_url)
            if refusal is not None:
                refusals.append(f"{source} {refusal}")
    finally:
        if owned:
            active.close()
    return PaperText(
        markdown=None,
        source="unavailable",
        page_url=None,
        reason="; ".join(refusals) if refusals else "neither source has rendered it",
    )


def convert_arxiv_html(html: str, page_url: str) -> str:
    """LaTeXML article HTML to markdown, keeping equations as their LaTeX.

    Every LaTeXML `math` element carries the original LaTeX in its `alttext`
    attribute, so replacing the element with that text keeps the equation
    legible without parsing the MathML tree it wraps.

    Raises `SourceUnreadable` when there is no article in the document. That
    is the check that matters rather than the status code: a bot challenge is
    served as HTTP 200 with a perfectly well-formed HTML body.
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(_ARTICLE_SELECTOR)
    if article is None:
        raise SourceUnreadable(
            f"'{page_url}' served no LaTeXML article, so it is not the paper"
        )

    for selector in _CHROME_SELECTORS:
        for node in article.select(selector):
            node.decompose()

    for element in article.find_all("math"):
        latex = str(element.get("alttext") or "").strip()
        if not latex:
            element.replace_with("")
            continue
        display = element.get("display") == "block"
        element.replace_with(f"$${latex}$$" if display else f"${latex}$")

    # The markdown leaves the site it came from, so a relative reference in it
    # would point at nothing. Images are referenced, not downloaded.
    for anchor in article.select("a[href]"):
        anchor["href"] = urljoin(page_url, str(anchor["href"]))
    for image in article.select("img[src]"):
        image["src"] = urljoin(page_url, str(image["src"]))

    markdown = markdownify(
        str(article),
        heading_style="ATX",
        escape_underscores=False,
        escape_asterisks=False,
        escape_misc=False,
    )
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def _rendering_at(client: httpx.Client, page_url: str) -> tuple[str | None, str | None]:
    """One source's markdown, and why there is none when there is none.

    A 404 is the expected "not rendered here" answer and reports nothing: a
    paper arXiv has simply not rendered is the ordinary case, and saying so
    for every such paper would be noise. Anything else is worth reporting,
    because a refusal - arXiv answers a burst of requests with 406, from an
    address-level throttle whose window is minutes rather than seconds - is
    not the same news as an absence, and the caller writes the same stub for
    both.
    """
    try:
        response = client.get(
            page_url, follow_redirects=True, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 404:
            return None, None
        return None, f"answered HTTP {status}"
    except httpx.HTTPError as error:
        return None, f"could not be reached: {error}"

    # What came back has to be HTML before it is parsed as HTML. Without this,
    # a source answering with XML - an Atom feed, an error document - is fed
    # to an HTML parser, which warns rather than failing, and under
    # `filterwarnings = ["error"]` that warning is raised from inside a
    # function whose contract is never to raise.
    content_type = response.headers.get("content-type", "text/html")
    if "html" not in content_type:
        return None, f"answered with {content_type.split(';')[0]}, not HTML"

    try:
        return convert_arxiv_html(response.text, page_url), None
    except SourceUnreadable as error:
        return None, str(error)
