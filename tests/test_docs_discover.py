"""Finding out which pages a documentation site has.

Three modes, tried cheapest and most authoritative first. A Sphinx site
publishes its own exact page list; any other site is reached through its
sitemap when it declares one, and by a bounded link-following crawl when it
does not. The bounds matter because this walks an arbitrary third-party site.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator

import httpx
import pytest

from kennis.engine.docs.discover import (
    _in_scope,
    crawl_site,
    discover_pages,
    discovery_mode,
    page_key,
    robots_for,
)
from kennis.engine.docs.http import USER_AGENT, TooLarge, get_within
from kennis.engine.docs.sites import DocsSite

BASE = "https://example.org/en/latest/"

SEARCHINDEX = (
    "Search.setIndex({"
    '"docnames": ["index", "install/index", "api/reference", "genindex"],'
    '"filenames": []'
    "});"
)

OPTIONS_JS = "var DOCUMENTATION_OPTIONS = {VERSION: '2.1.0', LANGUAGE: 'en'};"

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/en/latest/index.html</loc></url>
  <url><loc>https://example.org/en/latest/guide/start.html</loc></url>
  <url><loc>https://example.org/blog/announcement.html</loc></url>
</urlset>
"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.org/sitemap-pages.xml</loc></sitemap>
</sitemapindex>
"""


def a_site(
    *,
    base_url: str = BASE,
    exclude: tuple[str, ...] = (),
    discovery: str | None = None,
    path_prefix: str | None = None,
) -> DocsSite:
    return DocsSite(
        project="example",
        base_url=base_url,
        exclude=exclude,
        discovery=discovery,
        path_prefix=path_prefix,
    )


def serving(routes: dict[str, httpx.Response]) -> httpx.Client:
    """A client answering by URL substring, longest match first."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern in sorted(routes, key=len, reverse=True):
            if pattern in url:
                return routes[pattern]
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def linking(pages: dict[str, str]) -> httpx.Client:
    """A client serving an HTML page per URL, for crawl tests."""

    def handler(request: httpx.Request) -> httpx.Response:
        html = pages.get(str(request.url))
        if html is None:
            return httpx.Response(404)
        return httpx.Response(
            200, text=html, headers={"content-type": "text/html; charset=utf-8"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def page(*hrefs: str) -> str:
    links = "".join(f'<a href="{href}">x</a>' for href in hrefs)
    return f'<html><body><div role="main">{links}</div></body></html>'


# ---------------------------------------------------------------------------
# Page keys
# ---------------------------------------------------------------------------


def test_a_page_key_is_the_path_below_the_prefix_without_its_suffix():
    assert page_key(
        "https://example.org/en/latest/install/index.html", "/en/latest/"
    ) == ("install/index")


def test_the_prefix_itself_is_the_index_page():
    assert page_key("https://example.org/en/latest/", "/en/latest/") == "index"


def test_a_directory_url_and_its_html_form_share_one_key():
    """Deliberate: the two serve the same page, and a second copy under a
    second key would be a duplicate the natural key could not catch."""
    prefix = "/en/latest/"
    assert page_key("https://example.org/en/latest/guide/", prefix) == page_key(
        "https://example.org/en/latest/guide.html", prefix
    )


# ---------------------------------------------------------------------------
# Choosing a mode
# ---------------------------------------------------------------------------


def test_a_sphinx_site_is_recognised_by_its_search_index():
    client = serving({"searchindex.js": httpx.Response(200, text=SEARCHINDEX)})
    assert discovery_mode(client, BASE) == "sphinx"


def test_a_site_with_a_sitemap_but_no_search_index_uses_the_sitemap():
    client = serving(
        {
            "searchindex.js": httpx.Response(404),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
            "sitemap.xml": httpx.Response(200, text=SITEMAP),
        }
    )
    assert discovery_mode(client, BASE) == "sitemap"


def test_a_site_with_neither_is_crawled():
    client = serving({"robots.txt": httpx.Response(404)})
    assert discovery_mode(client, BASE) == "crawl"


def test_a_pinned_mode_is_not_probed():
    """The recorded mode is what a re-crawl uses, so the probe is skipped.

    robots.txt is still fetched: that is a separate question from which mode
    applies, and the answer is not one a recorded crawl scope may pin.
    """
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url).endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if str(request.url).endswith("sitemap.xml"):
            return httpx.Response(200, text=SITEMAP)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    site = a_site(discovery="sitemap")

    assert discover_pages(client, site).mode == "sitemap"
    assert not [url for url in requested if url.endswith("searchindex.js")]


# ---------------------------------------------------------------------------
# The Sphinx path
# ---------------------------------------------------------------------------


def test_sphinx_pages_come_from_the_search_index():
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "documentation_options.js": httpx.Response(200, text=OPTIONS_JS),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )
    found = discover_pages(client, a_site())

    assert found.mode == "sphinx"
    assert [item.key for item in found.pages] == [
        "index",
        "install/index",
        "api/reference",
    ]
    assert found.pages[0].url == "https://example.org/en/latest/index.html"


def test_sphinx_generated_pages_that_hold_no_documentation_are_dropped():
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )
    assert "genindex" not in [
        item.key for item in discover_pages(client, a_site()).pages
    ]


def test_an_exclude_pattern_drops_matching_pages():
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )
    site = a_site(exclude=("api/*",))
    assert [item.key for item in discover_pages(client, site).pages] == [
        "index",
        "install/index",
    ]


def test_the_version_comes_from_the_site_when_it_states_one():
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "documentation_options.js": httpx.Response(200, text=OPTIONS_JS),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )
    assert discover_pages(client, a_site()).version == "2.1.0"


def test_the_version_falls_back_to_the_slug_that_served_the_pages():
    """A project that sets no version publishes an empty string. The slug is
    true provenance where an invented version would not be."""
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "documentation_options.js": httpx.Response(404),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )
    assert discover_pages(client, a_site()).version == "latest"


# ---------------------------------------------------------------------------
# The sitemap path
# ---------------------------------------------------------------------------


def test_sitemap_pages_outside_the_prefix_are_dropped():
    """Same-origin alone would sweep a site's blog in beside its docs."""
    client = serving(
        {
            "searchindex.js": httpx.Response(404),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
            "sitemap.xml": httpx.Response(200, text=SITEMAP),
        }
    )
    found = discover_pages(client, a_site())

    assert found.mode == "sitemap"
    assert [item.key for item in found.pages] == [
        "en/latest/index",
        "en/latest/guide/start",
    ]


def test_a_sitemap_index_is_followed_to_the_sitemaps_it_names():
    client = serving(
        {
            "searchindex.js": httpx.Response(404),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
            "sitemap.xml": httpx.Response(200, text=SITEMAP_INDEX),
            "sitemap-pages.xml": httpx.Response(200, text=SITEMAP),
        }
    )
    assert [item.key for item in discover_pages(client, a_site()).pages] == [
        "en/latest/index",
        "en/latest/guide/start",
    ]


def test_a_sitemap_declared_in_robots_is_preferred_to_the_conventional_one():
    client = serving(
        {
            "searchindex.js": httpx.Response(404),
            "robots.txt": httpx.Response(
                200,
                text="User-agent: *\nAllow: /\nSitemap: https://example.org/sitemap-pages.xml\n",
            ),
            "sitemap-pages.xml": httpx.Response(200, text=SITEMAP),
        }
    )
    assert [item.key for item in discover_pages(client, a_site()).pages] == [
        "en/latest/index",
        "en/latest/guide/start",
    ]


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------


def test_the_crawl_follows_links_within_the_prefix():
    client = linking(
        {
            BASE: page("guide.html", "/blog/post.html", "https://elsewhere.org/x.html"),
            "https://example.org/en/latest/guide.html": page(),
        }
    )
    found = crawl_site(
        client, BASE, robots=robots_for(client, "https://example.org"), delay=0
    )

    assert found.urls == [BASE, "https://example.org/en/latest/guide.html"]


def test_the_crawl_stops_at_the_page_limit():
    pages = {BASE: page(*[f"p{index}.html" for index in range(10)])}
    for index in range(10):
        pages[f"https://example.org/en/latest/p{index}.html"] = page()
    client = linking(pages)

    found = crawl_site(
        client,
        BASE,
        robots=robots_for(client, "https://example.org"),
        max_pages=4,
        delay=0,
    )
    assert len(found.urls) == 4


def test_the_crawl_stops_at_the_depth_limit():
    client = linking(
        {
            BASE: page("one.html"),
            "https://example.org/en/latest/one.html": page("two.html"),
            "https://example.org/en/latest/two.html": page(),
        }
    )
    found = crawl_site(
        client,
        BASE,
        robots=robots_for(client, "https://example.org"),
        max_depth=1,
        delay=0,
    )
    assert found.urls == [BASE, "https://example.org/en/latest/one.html"]


def test_non_html_links_are_never_requested():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url).endswith(".pdf"):
            raise AssertionError("requested a pdf")
        return httpx.Response(
            200,
            text=page("paper.pdf", "logo.png", "style.css"),
            headers={"content-type": "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    crawl_site(client, BASE, robots=robots_for(client, "https://example.org"), delay=0)

    assert not [url for url in requested if url.endswith((".pdf", ".png", ".css"))]


def test_a_page_served_as_something_other_than_html_is_dropped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="{}", headers={"content-type": "application/json"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    found = crawl_site(
        client, BASE, robots=robots_for(client, "https://example.org"), delay=0
    )
    assert found.urls == []


def test_robots_disallow_is_obeyed():
    client = linking({BASE: page()})
    robots = robots_for(
        serving(
            {"robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /en/\n")}
        ),
        "https://example.org",
    )
    assert crawl_site(client, BASE, robots=robots, delay=0).urls == []


def test_an_unreachable_robots_file_does_not_stop_the_crawl():
    """Absent is not forbidden. A 401 or 403 is, and is handled separately."""
    client = serving({"robots.txt": httpx.Response(404)})
    assert robots_for(client, "https://example.org").can_fetch("kennis", BASE)


def test_robots_refusing_to_serve_itself_forbids_everything():
    client = serving({"robots.txt": httpx.Response(403)})
    assert not robots_for(client, "https://example.org").can_fetch("kennis", BASE)


def test_robots_is_consulted_on_the_sphinx_path_too():
    """A departure from boepie, which checks robots only when crawling. That
    a site publishes its page list says what exists, not what may be fetched.
    """
    client = serving(
        {
            "searchindex.js": httpx.Response(200, text=SEARCHINDEX),
            "robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /en/\n"),
        }
    )
    assert discover_pages(client, a_site()).pages == []


# ---------------------------------------------------------------------------
# The page limit, in the mode that ignored it
# ---------------------------------------------------------------------------


def a_sphinx_site_of(count: int) -> httpx.Client:
    docnames = ", ".join(f'"page{index}"' for index in range(count))
    return serving(
        {
            "searchindex.js": httpx.Response(
                200, text=f'Search.setIndex({{"docnames": [{docnames}]}});'
            ),
            "documentation_options.js": httpx.Response(200, text=OPTIONS_JS),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        }
    )


def test_sphinx_discovery_stops_at_the_page_limit():
    """Found by running the command. `--max-pages 5` against a real Sphinx
    site enumerated all 1433 of its pages and began fetching every one:
    `discover_pages` passed `max_pages` to the generic crawl and not to
    `_sphinx_pages`, which took no such argument.

    This is the mode that matters most for the bound, because it is the one
    that succeeds. A crawl walks links and stops; a Sphinx site hands over a
    complete list, so nothing else limits it.
    """
    found = discover_pages(a_sphinx_site_of(40), a_site(), max_pages=5, delay=0)

    assert found.mode == "sphinx"
    assert len(found.pages) == 5


def test_a_sphinx_site_under_the_limit_is_returned_whole():
    """The control: the cap truncates, it does not pad or reorder."""
    found = discover_pages(a_sphinx_site_of(3), a_site(), max_pages=300, delay=0)

    assert [page.key for page in found.pages] == ["page0", "page1", "page2"]


# ---------------------------------------------------------------------------
# Staying on the site (the review of 2026-10-13)
# ---------------------------------------------------------------------------

HTML = "text/html"


def routed(
    routes: dict[str, tuple[str, str] | str], asked: list[str] | None = None
) -> httpx.Client:
    """A site: a URL answers with (type, body), or with a string, which is
    where it redirects. Every URL asked for is recorded in `asked`."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if asked is not None:
            asked.append(url)
        answer = routes.get(url)
        if answer is None:
            return httpx.Response(404)
        if isinstance(answer, str):
            return httpx.Response(302, headers={"location": answer})
        kind, body = answer
        return httpx.Response(200, headers={"content-type": kind}, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_links_are_resolved_where_a_redirect_landed():
    """A root redirecting to `/en/latest/` resolved `install.html` one level
    too high, and only the index was added."""
    client = routed(
        {
            "https://proj.example.io/": "https://proj.example.io/en/latest/",
            "https://proj.example.io/en/latest/": (HTML, page("install.html")),
            "https://proj.example.io/en/latest/install.html": (HTML, page()),
        }
    )

    found = discover_pages(
        client,
        DocsSite(project="p", base_url="https://proj.example.io/", discovery="crawl"),
        delay=0,
    )

    assert "en/latest/install" in [found_page.key for found_page in found.pages]


def test_a_redirect_off_the_site_is_never_followed():
    """An in-scope page redirecting to `127.0.0.1` was fetched, filed under
    the documentation's address, and its links walked."""
    asked: list[str] = []
    client = routed(
        {
            "https://docs.example.org/guide/": (HTML, page("a.html")),
            "https://docs.example.org/guide/a.html": "http://127.0.0.1:8080/admin",
            "http://127.0.0.1:8080/admin": (HTML, page("secret.html")),
        },
        asked,
    )

    found = discover_pages(
        client,
        DocsSite(
            project="d", base_url="https://docs.example.org/guide/", discovery="crawl"
        ),
        delay=0,
    )

    assert not [url for url in asked if "127.0.0.1" in url]
    assert [found_page.key for found_page in found.pages] == ["guide"]


def test_a_sitemap_on_another_host_is_never_read():
    asked: list[str] = []
    client = routed(
        {
            "https://h.org/robots.txt": (
                "text/plain",
                "Sitemap: http://10.0.0.5/x.xml\n",
            )
        },
        asked,
    )

    discover_pages(
        client,
        DocsSite(project="h", base_url="https://h.org/docs/", discovery="sitemap"),
        delay=0,
    )

    assert not [url for url in asked if "10.0.0.5" in url]


def test_a_sphinx_docname_cannot_name_a_page_off_the_site_or_the_prefix():
    index = (
        "Search.setIndex("
        + json.dumps({"docnames": ["index", "//127.0.0.1:9000/x", "../../outside"]})
        + ")"
    )
    client = routed({"https://h.org/docs/searchindex.js": ("text/javascript", index)})

    found = discover_pages(
        client,
        DocsSite(project="h", base_url="https://h.org/docs/", discovery="sphinx"),
        delay=0,
    )

    assert [found_page.key for found_page in found.pages] == ["index"]


def test_a_sibling_directory_and_the_root_are_out_of_scope():
    """`startswith("/en/latest")` admitted `/en/latest-old/`, and the root
    was always admitted, taking the key `index` from the real index."""
    assert not _in_scope("https://h/en/latest-old/x", "https://h", "/en/latest/")
    assert not _in_scope("https://h/", "https://h", "/en/latest/")
    assert _in_scope("https://h/en/latest", "https://h", "/en/latest/")
    assert _in_scope("https://h/en/latest/x", "https://h", "/en/latest/")


def test_a_seed_without_its_slash_is_still_its_directory():
    """`https://h.org/docs` probed `https://h.org/searchindex.js` and took
    the whole origin as its scope."""
    index = "Search.setIndex(" + json.dumps({"docnames": ["index", "intro"]}) + ")"
    client = routed({"https://h.org/docs/searchindex.js": ("text/javascript", index)})

    found = discover_pages(
        client, DocsSite(project="h", base_url="https://h.org/docs"), delay=0
    )

    assert found.mode == "sphinx"
    assert found.path_prefix == "/docs/"
    assert [found_page.url for found_page in found.pages] == [
        "https://h.org/docs/index.html",
        "https://h.org/docs/intro.html",
    ]


def test_a_robots_file_that_errors_forbids_rather_than_allows():
    """A 500's error page parsed as rules allowed everything; RFC 9309 reads
    a server error as "may not crawl now"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="<html>Service Unavailable</html>")

    robots = robots_for(
        httpx.Client(transport=httpx.MockTransport(handler)), "https://h.org"
    )

    assert not robots.can_fetch("kennis-docs-fetch", "https://h.org/docs/")


# ---------------------------------------------------------------------------
# What one request may cost
# ---------------------------------------------------------------------------


def test_a_response_longer_than_the_limit_is_abandoned_part_way():
    """A release archive linked from the docs was read whole into memory
    before its content type was looked at."""
    sent: list[int] = []

    def endless() -> Iterator[bytes]:
        for _ in range(1000):
            sent.append(1)
            yield b"x" * 1024

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=endless())
        )
    )

    with pytest.raises(TooLarge):
        get_within(client, BASE, origin="https://example.org", limit=10 * 1024)
    assert len(sent) < 20


def test_a_declared_length_over_the_limit_is_refused_before_reading():
    client = serving(
        {BASE: httpx.Response(200, headers={"content-length": "999999"}, text="x")}
    )

    with pytest.raises(TooLarge):
        get_within(client, BASE, origin="https://example.org", limit=1000)


def test_a_compressed_response_is_measured_as_it_inflates():
    """A small gzip body can inflate to any size; the bytes counted are the
    ones that would be held."""
    packed = gzip.compress(b"x" * 100_000)
    client = serving(
        {
            BASE: httpx.Response(
                200, headers={"content-encoding": "gzip"}, content=packed
            )
        }
    )

    with pytest.raises(TooLarge):
        get_within(client, BASE, origin="https://example.org", limit=10_000)


def test_a_response_within_the_limit_reads_as_it_was_sent():
    client = serving(
        {
            BASE: httpx.Response(
                200,
                headers={
                    "content-encoding": "gzip",
                    "content-type": "text/html; charset=utf-8",
                },
                content=gzip.compress("caf\u00e9".encode()),
            )
        }
    )

    response = get_within(client, BASE, origin="https://example.org")

    assert response.text == "caf\u00e9"
    assert str(response.url) == BASE


def test_a_page_too_large_to_read_is_skipped_by_the_crawl():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        html = page("big.html", "small.html") if url == BASE else page()
        headers = {"content-type": "text/html"}
        if url.endswith("big.html"):
            headers["content-length"] = str(10**12)
        return httpx.Response(200, text=html, headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    robots = robots_for(serving({}), "https://example.org")

    urls = crawl_site(client, BASE, robots=robots, delay=0).urls

    assert BASE + "big.html" not in urls
    assert BASE + "small.html" in urls


def test_the_user_agent_says_what_it_is_and_where_to_ask():
    assert USER_AGENT.startswith("kennis-docs-fetch/")
    assert "https://" in USER_AGENT


def test_a_page_has_one_key_whichever_address_the_add_started_from():
    """Keyed below the seed, a site added from `/en/latest/` and again from
    `/en/latest/guide/` filed its guide twice: `guide/start` and `start`."""
    client = serving(
        {
            "searchindex.js": httpx.Response(404),
            "robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
            "sitemap.xml": httpx.Response(200, text=SITEMAP),
        }
    )

    from_root = discover_pages(client, a_site())
    from_section = discover_pages(client, a_site(base_url=BASE + "guide/"))

    assert [page.key for page in from_section.pages] == ["en/latest/guide/start"]
    assert set(page.key for page in from_section.pages) <= set(
        page.key for page in from_root.pages
    )


def test_a_seed_inside_a_sphinx_site_finds_its_root():
    """Its pages are named below the root by the site itself, so a seed in a
    section keys them as the root would, and only that section is added."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if str(request.url) == BASE + "searchindex.js":
            return httpx.Response(200, text=SEARCHINDEX)
        if request.url.path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    found = discover_pages(client, a_site(base_url=BASE + "install/"))

    assert found.mode == "sphinx"
    assert [page.key for page in found.pages] == ["install/index"]
    assert found.pages[0].url == BASE + "install/index.html"
