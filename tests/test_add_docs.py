"""Adding documentation: notes plus site structure.

A docs page's identity is its project and its page key, so the surrogate
identifier is derived from the pair rather than minted. That is what makes
re-adding a site report every page unchanged instead of writing a second copy
of the site.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, add_docs
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.ids import derive_id, natural_key_for_docs
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.errors import InputError
from kennis.engine.events import ItemFinished, Outcome, Recorder

BASE = "https://example.org/en/latest/"

SEARCHINDEX = (
    'Search.setIndex({"docnames": ["index", "guide/start"], "filenames": []});'
)

OPTIONS_JS = "var DOCUMENTATION_OPTIONS = {VERSION: '2.1.0'};"


def a_page(title: str) -> str:
    return (
        '<html><body><div role="main">'
        f"<h1>{title}</h1><p>Body of {title}.</p>"
        "</div></body></html>"
    )


def sphinx_site() -> httpx.Client:
    """A two-page Sphinx site, answering on whatever host it is asked about.

    Keyed by path rather than by full URL, so a test that varies the host to
    exercise project naming still gets its pages served.
    """
    pages = {
        "/en/latest/index.html": a_page("Overview"),
        "/en/latest/guide/start.html": a_page("Getting started"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("searchindex.js"):
            return httpx.Response(200, text=SEARCHINDEX)
        if path.endswith("documentation_options.js"):
            return httpx.Response(200, text=OPTIONS_JS)
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        html = pages.get(path)
        if html is None:
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def docs(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="docs")


def pages_of(docs: Collection) -> dict[str, DocsFrontmatter]:
    found: dict[str, DocsFrontmatter] = {}
    for document in docs.contents().documents:
        frontmatter = document.frontmatter
        assert isinstance(frontmatter, DocsFrontmatter)
        found[frontmatter.docs.page] = frontmatter
    return found


# ---------------------------------------------------------------------------
# Adding a site
# ---------------------------------------------------------------------------


def test_every_page_of_a_site_becomes_a_document(docs: Collection):
    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    assert [outcome.outcome for outcome in report.outcomes] == [
        Outcome.ADDED,
        Outcome.ADDED,
    ]
    assert set(pages_of(docs)) == {"index", "guide/start"}


def test_a_page_records_its_project_and_page_key(docs: Collection):
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    frontmatter = pages_of(docs)["guide/start"]
    assert frontmatter.docs.project == "example"
    assert frontmatter.docs.page == "guide/start"
    assert frontmatter.docs.base_url == BASE
    assert frontmatter.docs.version == "2.1.0"


def test_the_identifier_is_derived_from_the_project_and_the_page(docs: Collection):
    """Two machines crawling the same site write the same identifier, so git
    has nothing to resolve."""
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    frontmatter = pages_of(docs)["index"]
    key = natural_key_for_docs(project="example", page="index")
    assert frontmatter.id == derive_id(key)
    assert frontmatter.id_from == key


def test_the_pages_are_filed_under_the_project(docs: Collection):
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    written = [path.relative_to(docs.path) for path in docs.path.rglob("*.md")]
    assert all(path.parts[0] == "example" for path in written)


def test_the_crawl_scope_is_recorded_on_every_page(docs: Collection):
    """The one thing a page cannot reconstruct about its own project, so a
    re-crawl needs no flags typed again."""
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    for frontmatter in pages_of(docs).values():
        assert frontmatter.docs.crawl is not None
        assert frontmatter.docs.crawl.discovery == "sphinx"


def test_the_body_is_the_page_prose(docs: Collection):
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    document = docs.resolve(pages_of(docs)["index"].id)
    assert "Body of Overview." in document.body


# ---------------------------------------------------------------------------
# Adding the same site twice
# ---------------------------------------------------------------------------


def test_re_adding_a_site_changes_nothing(docs: Collection):
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )
    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    assert set(report.counts) == {Outcome.UNCHANGED}
    assert len(pages_of(docs)) == 2


def test_a_duplicate_page_is_reported_not_failed(docs: Collection):
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )
    recorder = Recorder()
    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
        events=recorder,
    )

    finished = [event for event in recorder.events if isinstance(event, ItemFinished)]
    assert {event.outcome for event in finished} == {Outcome.UNCHANGED}


# ---------------------------------------------------------------------------
# Naming the project
# ---------------------------------------------------------------------------


def test_the_project_is_derived_from_the_host_when_it_is_not_given(docs: Collection):
    add_docs(
        docs,
        ["https://stimela.readthedocs.io/en/latest/"],
        AddOptions(request_delay_seconds=0),
        client=sphinx_site(),
    )

    assert {frontmatter.docs.project for frontmatter in pages_of(docs).values()} == {
        "stimela"
    }


def test_a_project_name_that_is_not_a_safe_path_component_is_refused(
    docs: Collection,
):
    """The name becomes a directory, so `../evil` has to be refused before it
    is used as one."""
    with pytest.raises(InputError):
        add_docs(docs, [BASE], AddOptions(project="../evil"), client=sphinx_site())


# ---------------------------------------------------------------------------
# A page that cannot be had
# ---------------------------------------------------------------------------


def test_a_page_that_fails_does_not_cost_the_others(docs: Collection):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("searchindex.js"):
            return httpx.Response(200, text=SEARCHINDEX)
        if url.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url.endswith("guide/start.html"):
            return httpx.Response(500)
        return httpx.Response(
            200, text=a_page("Overview"), headers={"content-type": "text/html"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=client,
    )

    assert report.counts == {Outcome.ADDED: 1, Outcome.FAILED: 1}
    assert set(pages_of(docs)) == {"index"}


def test_a_challenge_page_is_not_written_as_documentation(docs: Collection):
    """Status 200 with an HTML body is what a bot check returns. Without the
    container check, its text would become a document."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("searchindex.js"):
            return httpx.Response(200, text=SEARCHINDEX)
        if url.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            text="<html><body><h1>Just a moment...</h1></body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=client,
    )

    assert set(report.counts) == {Outcome.FAILED}
    assert pages_of(docs) == {}


# ---------------------------------------------------------------------------
# A local page filed into a project
# ---------------------------------------------------------------------------


def test_a_local_markdown_file_can_be_filed_into_a_project(
    docs: Collection, tmp_path: Path
):
    """Source and collection are independent: a docs project can be extended
    with a tutorial that was never on the site."""
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n\nWritten by hand.\n", encoding="utf-8")

    add_docs(
        docs, [str(tutorial)], AddOptions(project="example", request_delay_seconds=0)
    )

    frontmatter = pages_of(docs)["tutorial"]
    assert frontmatter.docs.project == "example"
    assert frontmatter.docs.base_url is None


def test_a_local_page_needs_a_project(docs: Collection, tmp_path: Path):
    """There is no host to derive one from."""
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n", encoding="utf-8")

    with pytest.raises(InputError):
        add_docs(docs, [str(tutorial)])


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------


def test_the_pages_of_a_site_are_spaced(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """The Sphinx and sitemap paths know every page up front, so without this
    they request all of them back to back - the traffic pattern the delay
    exists to avoid."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5),
        client=sphinx_site(),
    )

    # Two pages, so one wait: the first costs nothing to ask for.
    assert slept == [0.5]


def test_a_page_the_crawl_already_holds_costs_no_wait(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """A crawl downloads a page to find the next one, so converting it later
    makes no request - and a wait without a request is only a slower add."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )
    crawled = a_page("Overview").replace(
        "</div>", '<a href="guide.html">next</a></div>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if path.endswith(("searchindex.js", "sitemap.xml")):
            return httpx.Response(404)
        return httpx.Response(200, text=crawled, headers={"content-type": "text/html"})

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5, max_depth=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    # Every wait recorded belongs to the crawl itself, not to the write loop.
    assert docs.contents().documents
    assert len(slept) == len(docs.contents().documents)


def test_an_offline_add_is_not_paced(docs: Collection, monkeypatch: pytest.MonkeyPatch):
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
    )

    assert slept == []
