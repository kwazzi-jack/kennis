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
from dataclasses import dataclass, field, replace
from fnmatch import fnmatch
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from kennis.engine.courtesy import crawl_delay, robots_for
from kennis.engine.docs.http import USER_AGENT, get_within
from kennis.engine.docs.sites import DocsSite

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
    # Seconds between requests to this site: the caller's, or longer when
    # its robots.txt asks for longer. The pages left to fetch are paced by it.
    delay: float = _FETCH_DELAY_SECONDS


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
    paced = paced_by(robots, delay)

    if mode == "sphinx":
        found = _sphinx_pages(client, site, prefix, robots, max_pages=max_pages)
    else:
        found = _generic_pages(
            client,
            site,
            prefix,
            robots,
            mode=mode,
            delay=paced,
            max_pages=max_pages,
            max_depth=max_depth,
        )
    return replace(found, delay=paced)


def paced_by(robots: RobotFileParser, delay: float) -> float:
    """`delay`, or the site's own `Crawl-delay` when that is longer.

    Read but ignored before, so a site asking for ten seconds between
    requests got one every fifth of a second.
    """
    return max(delay, crawl_delay(robots, USER_AGENT))


def discovery_mode(client: httpx.Client, base_url: str) -> str:
    """ "sphinx", "sitemap" or "crawl", cheapest and most authoritative first."""
    if _sphinx_root(client, base_url) is not None:
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

    # Every request counts, not only those that found a page: a page of a
    # thousand dead links was a thousand requests, unpaced and uncounted.
    attempts = 0
    while queue and len(found) < max_pages and attempts < max_pages * 3:
        url, depth = queue.pop(0)
        key = _normalized(url)
        if key in visited:
            continue
        visited.add(key)
        if not robots.can_fetch(USER_AGENT, url):
            continue

        if attempts and delay:
            time.sleep(delay)
        attempts += 1
        try:
            response = get_within(client, url, origin=origin)
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        if "html" not in response.headers.get("content-type", ""):
            continue
        # Where the page really is, after any redirect: its links are
        # relative to that, and a site's root redirecting to `/en/latest/`
        # resolved every link one level too high.
        landed = str(response.url)
        if landed != url and (
            not _in_scope(_normalized(landed), origin, prefix)
            or not robots.can_fetch(USER_AGENT, landed)
        ):
            continue

        found.append(url)
        html[url] = response.text
        if depth >= max_depth:
            continue

        for link in _links_in(response.text, landed):
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
    found = _sphinx_root(client, site.base_url)
    base, docnames = found if found is not None else (site.base_url, [])
    pages = [
        DiscoveredPage(key=docname, url=urljoin(base, f"{docname}.html"))
        for docname in docnames
        if not _excluded(docname, site.exclude)
    ]
    # In scope as well as allowed: a docname is the site's own data, and
    # `../../outside` or `//another-host/x` named a page off the site.
    origin = _origin_of(site.base_url)
    allowed = [
        page
        for page in pages
        if _in_scope(_normalized(page.url), origin, prefix)
        and robots.can_fetch(USER_AGENT, page.url)
    ]
    return Discovery(
        mode="sphinx",
        version=_sphinx_version(client, base),
        pages=allowed[:max_pages],
        path_prefix=prefix,
    )


# How far above the seed a Sphinx site's root is looked for: a seed is
# usually the root or a section of it, rarely more than a few levels down.
_MAX_ROOT_DEPTH: Final = 4


def _sphinx_root(client: httpx.Client, seed: str) -> tuple[str, list[str]] | None:
    """The Sphinx site the seed is in - the directory holding its search
    index - and every page name it publishes, or None if it is not one.

    Looked for upwards from the seed, not only at it. A page's key is its
    name below this root, so the same page is filed under the same key
    whichever address the add started from; keyed below the seed, a site
    added from `/en/latest/` and again from `/en/latest/guide/` was two
    copies of its guide.
    """
    directory = _as_directory(seed)
    for _ in range(_MAX_ROOT_DEPTH + 1):
        docnames = _docnames(client, directory)
        if docnames is not None:
            return directory, docnames
        parent = urljoin(directory, "..")
        if parent == directory:
            return None
        directory = parent
    return None


def _docnames(client: httpx.Client, base_url: str) -> list[str] | None:
    """Every page name the site publishes, or None if it is not a Sphinx site."""
    try:
        response = get_within(
            client, urljoin(base_url, "searchindex.js"), origin=_origin_of(base_url)
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
        response = get_within(
            client,
            urljoin(base_url, "_static/documentation_options.js"),
            origin=_origin_of(base_url),
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
            for url in _sitemap_pages(
                client, _sitemap_urls(client, origin, robots), origin=origin
            )
            if _in_scope(_normalized(url), origin, prefix)
            and robots.can_fetch(USER_AGENT, url)
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
        # Bounded as the other two modes are: a sitemap lists every page a
        # site has, and nothing else stopped a 10 000-page one being
        # fetched whole.
        if len(pages) >= max_pages:
            break
        # The whole path, not the path below the seed: these modes have no
        # root of their own to key against, and below the seed the same page
        # had a different key for every address an add started from.
        key = page_key(url, "/")
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
        response = get_within(client, fallback, origin=origin)
    except httpx.HTTPError:
        return []
    return [fallback] if response.status_code == 200 else []


def _sitemap_pages(
    client: httpx.Client, sitemap_urls: list[str], *, origin: str
) -> list[str]:
    """The page URLs one or more sitemap files list.

    `sitemapindex` nesting is followed, bounded by the number of files read so
    a sitemap that points at itself cannot loop. Only files on the site's own
    origin are read: a `Sitemap:` line or a `<loc>` may name any host.
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
            response = get_within(client, url, origin=origin)
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


def _as_directory(url: str) -> str:
    """`url` with the slash a directory written without one is missing, so
    names joined to it land inside it: `https://h.org/docs` and
    `searchindex.js` gave `https://h.org/searchindex.js`."""
    parsed = urlsplit(url)
    last = parsed.path.rsplit("/", 1)[-1]
    if not parsed.path or parsed.path.endswith("/") or "." in last:
        return url
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path + "/", parsed.query, "")
    )


def _path_prefix_of(base_url: str) -> str:
    """The seed URL's directory, so `.../en/latest/index.html` gives
    `/en/latest/`. A seed that is already the site root gives `/`, which costs
    nothing on a host that serves only documentation."""
    path = urlsplit(base_url).path
    if not path or path.endswith("/"):
        return path or "/"
    # `https://h.org/docs` is the docs directory, written without its
    # slash; read as a file it gave the prefix `/` and the whole origin.
    last = path.rsplit("/", 1)[1]
    if "." not in last:
        return path + "/"
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
    # The prefix as a directory: `startswith("/en/latest")` admitted
    # `/en/latest-old/`, and the root was always admitted, where in sitemap
    # mode it took the key `index` from the documentation's own index.
    directory = path_prefix.rstrip("/")
    return (
        not directory
        or parsed.path == directory
        or parsed.path.startswith(directory + "/")
    )


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
