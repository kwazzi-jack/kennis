"""Which pages a documentation site has.

Three modes, tried cheapest and most authoritative first. A Sphinx site
publishes its own exact page list in `searchindex.js`, so nothing is guessed.
Any other site is reached through the sitemap it declares, and only failing
that by a bounded link-following crawl. The mode is recorded on every page
written, so a re-crawl repeats the walk that was actually taken rather than
probing again.

The bounds are not incidental. This walks an arbitrary third-party site, so
the crawl is limited in pages, in depth and in the number of sitemap files it
will follow, it is scoped to one origin *and* one path prefix, and every
request is spaced by a politeness delay.

**Serial rather than concurrent.** Design section 20 recommends that the
fetchers use concurrency internally and present a synchronous interface. They
do not here, because the politeness delay is the binding constraint and a
docs add targets a single host: parallel requests are exactly the traffic
pattern the delay exists to avoid. Concurrency pays across many hosts, which
is a later milestone's `corpus sync` over several projects.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from kennis.engine.docs.sites import DocsSite

_USER_AGENT: Final = "kennis-docs-fetch"
_REQUEST_TIMEOUT_SECONDS: Final = 30

# Spacing between requests to one host. Politeness, and the reason this layer
# is serial rather than concurrent.
_FETCH_DELAY_SECONDS: Final = 0.2

# Walking a third-party site, so every axis is bounded.
_MAX_PAGES: Final = 300
_MAX_DEPTH: Final = 5
_MAX_SITEMAP_FILES: Final = 50

_SITEMAP_NS: Final = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Page names every Sphinx site generates that hold no documentation of their
# own, so they are never worth a request.
_ALWAYS_EXCLUDE: Final = ("genindex", "py-modindex", "modindex", "search")

# Skipped by extension before being requested, and again by Content-Type
# after, because an extension is a hint rather than a promise.
_NON_HTML_SUFFIXES: Final = (
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".css",
    ".js",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".mp3",
    ".wav",
    ".avi",
    ".xml",
    ".txt",
    ".rst",
    ".json",
)


# The two answers a missing or refused robots.txt stands for, written as
# robots bodies rather than set on the parser's `allow_all`/`disallow_all`
# attributes: those exist at runtime but are not part of the declared
# interface, and parsing an equivalent body is the same behaviour through the
# documented one. An empty body matches nothing, so everything is allowed.
_ALLOW_EVERYTHING: Final = ()
_FORBID_EVERYTHING: Final = ("User-agent: *", "Disallow: /")


@dataclass(frozen=True, slots=True)
class DiscoveredPage:
    """One page a site offers: the key it will be filed under, and its URL."""

    key: str
    url: str


@dataclass(frozen=True, slots=True)
class Crawled:
    """What a crawl visited, and the HTML it already holds for each page.

    The HTML is carried rather than discarded because a link-following crawl
    has to download a page to find the next one, so converting it afterwards
    from a second request would fetch every page twice.
    """

    urls: list[str]
    html: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Discovery:
    """Every page of one site, and how they were found."""

    mode: str
    version: str | None
    pages: list[DiscoveredPage]
    path_prefix: str
    # Pages already downloaded while discovering, keyed by URL.
    html: dict[str, str] = field(default_factory=dict)


def discover_pages(
    client: httpx.Client,
    site: DocsSite,
    *,
    delay: float = _FETCH_DELAY_SECONDS,
    max_pages: int = _MAX_PAGES,
    max_depth: int = _MAX_DEPTH,
) -> Discovery:
    """Every page of `site`, by whichever mode applies.

    `site.discovery` pins the mode when it is set - which is what a page's
    recorded crawl scope supplies on a re-crawl - and it is probed otherwise.
    """
    mode = site.discovery or discovery_mode(client, site.base_url)
    prefix = site.path_prefix or _path_prefix_of(site.base_url)
    robots = robots_for(client, _origin_of(site.base_url))

    if mode == "sphinx":
        return _sphinx_pages(client, site, prefix, robots, max_pages=max_pages)
    return _generic_pages(
        client,
        site,
        prefix,
        robots,
        mode=mode,
        delay=delay,
        max_pages=max_pages,
        max_depth=max_depth,
    )


def discovery_mode(client: httpx.Client, base_url: str) -> str:
    """ "sphinx", "sitemap" or "crawl", cheapest and most authoritative first."""
    if _docnames(client, base_url) is not None:
        return "sphinx"
    origin = _origin_of(base_url)
    robots = robots_for(client, origin)
    if _sitemap_urls(client, origin, robots):
        return "sitemap"
    return "crawl"


def page_key(url: str, path_prefix: str) -> str:
    """The key a page is filed under: its path below `path_prefix`.

    Any `.html` suffix is dropped and any trailing slash collapsed, so a site
    serving a page at both `guide/` and `guide.html` yields one key rather
    than two documents of the same content. The prefix itself is `index`.
    """
    path = urlsplit(url).path
    relative = (
        path[len(path_prefix) :] if path.startswith(path_prefix) else path.lstrip("/")
    )
    relative = relative.strip("/")
    for suffix in (".html", ".htm"):
        if relative.endswith(suffix):
            relative = relative[: -len(suffix)]
            break
    return relative.strip("/") or "index"


def robots_for(client: httpx.Client, origin: str) -> RobotFileParser:
    """`{origin}/robots.txt`, parsed.

    Fetched through the caller's own client rather than through
    `urllib.robotparser`'s `urlopen`, which means replicating by hand the
    status handling it would have done: refusing to serve robots.txt at all
    (401 or 403) forbids everything, any other client error allows
    everything, and an unreachable file is absent rather than forbidding.
    """
    parser = RobotFileParser()
    robots_url = urljoin(origin + "/", "robots.txt")
    parser.set_url(robots_url)
    try:
        response = client.get(robots_url, timeout=_REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        parser.parse(_ALLOW_EVERYTHING)
        return parser

    if response.status_code in (401, 403):
        parser.parse(_FORBID_EVERYTHING)
    elif 400 <= response.status_code < 500:
        parser.parse(_ALLOW_EVERYTHING)
    else:
        parser.parse(response.text.splitlines())
    return parser


def crawl_site(
    client: httpx.Client,
    base_url: str,
    *,
    robots: RobotFileParser,
    path_prefix: str | None = None,
    max_pages: int = _MAX_PAGES,
    max_depth: int = _MAX_DEPTH,
    delay: float = _FETCH_DELAY_SECONDS,
) -> Crawled:
    """A bounded, breadth-first, robots-respecting walk from `base_url`.

    Scope is same-origin **and** same-path-prefix. Same-origin alone would
    sweep a project's blog and marketing pages in beside its documentation,
    which is a difference of kind rather than of degree once it is indexed.
    """
    origin = _origin_of(base_url)
    prefix = path_prefix if path_prefix is not None else _path_prefix_of(base_url)

    # Deduplication is on the normalised URL, but every request uses the URL
    # as it was discovered: normalising collapses a directory's trailing
    # slash, which is not always safe to use as the literal target.
    visited: set[str] = set()
    queued: set[str] = {_normalized(base_url)}
    queue: list[tuple[str, int]] = [(base_url, 0)]
    found: list[str] = []
    html: dict[str, str] = {}

    while queue and len(found) < max_pages:
        url, depth = queue.pop(0)
        key = _normalized(url)
        if key in visited:
            continue
        visited.add(key)
        if not robots.can_fetch(_USER_AGENT, url):
            continue

        try:
            response = client.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        if "html" not in response.headers.get("content-type", ""):
            continue

        found.append(url)
        html[url] = response.text
        if delay:
            time.sleep(delay)
        if depth >= max_depth:
            continue

        for link in _links_in(response.text, url):
            normalized = _normalized(link)
            if normalized in queued or normalized in visited:
                continue
            if not _in_scope(normalized, origin, prefix):
                continue
            queued.add(normalized)
            queue.append((link, depth + 1))

    return Crawled(urls=found, html=html)


# ---------------------------------------------------------------------------
# The Sphinx path
# ---------------------------------------------------------------------------


def _sphinx_pages(
    client: httpx.Client,
    site: DocsSite,
    prefix: str,
    robots: RobotFileParser,
    *,
    max_pages: int,
) -> Discovery:
    """The site's own page list, from the index it built for its own search.

    Unlike boepie, robots.txt is consulted here as well as on the crawl. That
    a site publishes what pages exist is a different statement from what may
    be fetched, and only the second is robots.txt's to make.

    **The limit applies here too, and this is the mode that most needs it.**
    A crawl walks links and stops when it runs out of them; a Sphinx site
    hands over a complete list, so nothing else bounds the fetch that
    follows. Without this a `--max-pages 5` against a 1433-page site
    enumerated all of them and began fetching every one.

    Truncated after the robots filter rather than before, so the limit counts
    pages that may actually be fetched.
    """
    docnames = _docnames(client, site.base_url) or []
    pages = [
        DiscoveredPage(key=docname, url=urljoin(site.base_url, f"{docname}.html"))
        for docname in docnames
        if not _excluded(docname, site.exclude)
    ]
    allowed = [page for page in pages if robots.can_fetch(_USER_AGENT, page.url)]
    return Discovery(
        mode="sphinx",
        version=_sphinx_version(client, site.base_url),
        pages=allowed[:max_pages],
        path_prefix=prefix,
    )


def _docnames(client: httpx.Client, base_url: str) -> list[str] | None:
    """Every page name the site publishes, or None if it is not a Sphinx site."""
    try:
        response = client.get(
            urljoin(base_url, "searchindex.js"), timeout=_REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    match = re.search(r"Search\.setIndex\((.*)\)\s*;?\s*$", response.text.strip(), re.S)
    if match is None:
        return None
    try:
        index = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(index, dict):
        return None
    docnames = index.get("docnames")
    if not isinstance(docnames, list):
        return None
    return [name for name in docnames if isinstance(name, str)]


def _sphinx_version(client: httpx.Client, base_url: str) -> str | None:
    """The project's own version string, or the slug that served these pages.

    Sphinx writes `VERSION` into `_static/documentation_options.js`, but only
    when the project sets one; plenty publish an empty string. Falling back to
    the URL's own slug keeps the recorded provenance true where an invented
    version would not be.
    """
    try:
        response = client.get(
            urljoin(base_url, "_static/documentation_options.js"),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        match = re.search(r"VERSION:\s*['\"]([^'\"]+)['\"]", response.text)
    except httpx.HTTPError:
        match = None
    if match is not None:
        return match.group(1)
    labels = [part for part in base_url.rstrip("/").split("/") if part]
    return labels[-1] if labels else None


# ---------------------------------------------------------------------------
# The sitemap and crawl paths
# ---------------------------------------------------------------------------


def _generic_pages(
    client: httpx.Client,
    site: DocsSite,
    prefix: str,
    robots: RobotFileParser,
    *,
    mode: str,
    delay: float,
    max_pages: int,
    max_depth: int,
) -> Discovery:
    origin = _origin_of(site.base_url)
    html: dict[str, str] = {}

    if mode == "sitemap":
        urls = [
            url
            for url in _sitemap_pages(client, _sitemap_urls(client, origin, robots))
            if _in_scope(_normalized(url), origin, prefix)
            and robots.can_fetch(_USER_AGENT, url)
        ]
    else:
        crawled = crawl_site(
            client,
            site.base_url,
            robots=robots,
            path_prefix=prefix,
            max_pages=max_pages,
            max_depth=max_depth,
            delay=delay,
        )
        urls = crawled.urls
        html = crawled.html

    pages: list[DiscoveredPage] = []
    seen: set[str] = set()
    for url in urls:
        key = page_key(url, prefix)
        if key in seen or _excluded(key, site.exclude):
            continue
        seen.add(key)
        pages.append(DiscoveredPage(key=key, url=url))

    return Discovery(
        mode=mode,
        version=None,
        pages=pages,
        path_prefix=prefix,
        html=html,
    )


def _sitemap_urls(
    client: httpx.Client, origin: str, robots: RobotFileParser
) -> list[str]:
    """Sitemap files to read.

    A `Sitemap:` directive in robots.txt is trusted without a further check,
    because the site announced it. The conventional `/sitemap.xml` is only
    used after confirming something is served there.
    """
    declared = list(robots.site_maps() or [])
    if declared:
        return declared

    fallback = urljoin(origin + "/", "sitemap.xml")
    try:
        response = client.get(fallback, timeout=_REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return []
    return [fallback] if response.status_code == 200 else []


def _sitemap_pages(client: httpx.Client, sitemap_urls: list[str]) -> list[str]:
    """The page URLs one or more sitemap files list.

    `sitemapindex` nesting is followed, bounded by the number of files read so
    a sitemap that points at itself cannot loop.
    """
    pages: list[str] = []
    read: set[str] = set()
    queue = list(sitemap_urls)

    while queue and len(read) < _MAX_SITEMAP_FILES:
        url = queue.pop(0)
        if url in read:
            continue
        read.add(url)
        try:
            response = client.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
        except (httpx.HTTPError, ElementTree.ParseError):
            continue

        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "sitemapindex":
            queue.extend(_locations(root, "sm:sitemap/sm:loc"))
        elif tag == "urlset":
            pages.extend(_locations(root, "sm:url/sm:loc"))
    return pages


def _locations(root: ElementTree.Element, path: str) -> list[str]:
    return [
        element.text.strip()
        for element in root.findall(f".//{path}", _SITEMAP_NS)
        if element.text
    ]


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _path_prefix_of(base_url: str) -> str:
    """The seed URL's directory, so `.../en/latest/index.html` gives
    `/en/latest/`. A seed that is already the site root gives `/`, which costs
    nothing on a host that serves only documentation."""
    path = urlsplit(base_url).path
    if not path or path.endswith("/"):
        return path or "/"
    return path.rsplit("/", 1)[0] + "/"


def _normalized(url: str) -> str:
    """Fragment and query stripped, trailing slash collapsed, for dedup."""
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "")
    )


def _in_scope(normalized_url: str, origin: str, path_prefix: str) -> bool:
    parsed = urlsplit(normalized_url)
    if f"{parsed.scheme}://{parsed.netloc}" != origin:
        return False
    return parsed.path.startswith(path_prefix.rstrip("/")) or parsed.path == "/"


def _links_in(html: str, page_url: str) -> list[str]:
    from bs4 import BeautifulSoup

    links: list[str] = []
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        href = str(anchor.get("href") or "")
        if not href:
            continue
        link = urljoin(page_url, href)
        parsed = urlsplit(link)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.path.lower().endswith(_NON_HTML_SUFFIXES):
            continue
        links.append(link)
    return links


def _excluded(key: str, exclude: tuple[str, ...]) -> bool:
    return any(fnmatch(key, pattern) for pattern in exclude + _ALWAYS_EXCLUDE)
