"""Finding out which pages a documentation site has.

Three modes, tried cheapest and most authoritative first. A Sphinx site
publishes its own exact page list; any other site is reached through its
sitemap when it declares one, and by a bounded link-following crawl when it
does not. The bounds matter because this walks an arbitrary third-party site.
"""

from __future__ import annotations

import httpx

from kennis.engine.docs.discover import (
    crawl_site,
    discover_pages,
    discovery_mode,
    page_key,
    robots_for,
)
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
    assert [item.key for item in found.pages] == ["index", "guide/start"]


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
        "index",
        "guide/start",
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
        "index",
        "guide/start",
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
