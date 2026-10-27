"""Adding documentation: notes plus site structure.

A docs page's identity is its project and its page key, so the surrogate
identifier is derived from the pair rather than minted. That is what makes
re-adding a site report every page unchanged instead of writing a second copy
of the site.
"""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, add_docs
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.ids import derive_id, natural_key_for_docs
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.errors import InputError
from kennis.engine.events import (
    Diagnostic,
    ItemFinished,
    NoPagesDiscovered,
    Outcome,
    Progress,
    Recorder,
    Severity,
)

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


def sphinx_site(robots: str = "User-agent: *\nAllow: /\n") -> httpx.Client:
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
            return httpx.Response(200, text=robots)
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
    assert frontmatter.docs.version == "latest"
    assert frontmatter.docs.release == "2.1.0"


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
    key = natural_key_for_docs(project="example", version="latest", page="index")
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
        docs,
        [str(tutorial)],
        AddOptions(project="example", version="latest", request_delay_seconds=0),
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


def test_a_local_page_without_a_project_is_refused_before_any_site_is_read(
    docs: Collection, tmp_path: Path
):
    """Checked in turn, a site listed first was crawled whole before the
    local page after it was refused, and the crawl thrown away."""
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n", encoding="utf-8")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(404)

    with pytest.raises(InputError, match=r"tutorial\.md"):
        add_docs(
            docs,
            [BASE, str(tutorial)],
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    assert requested == []


def test_an_address_of_a_file_is_one_document_not_a_site(docs: Collection):
    """Every URL was a site to crawl, so a link to one markdown file or PDF
    walked the whole site it sat on and never added the file itself."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(
            200,
            text="# Calibration guide\n\nSteps.\n",
            headers={"content-type": "text/markdown"},
        )

    address = "https://example.org/en/latest/guides/calibration.md"
    report = add_docs(
        docs,
        [address],
        AddOptions(project="example"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert asked == [address]
    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED]
    [page] = docs.contents().documents
    assert page.frontmatter.docs.project == "example"
    assert page.frontmatter.title == "Calibration guide"


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

    # Two pages, so one wait: the first costs nothing to ask for. The delay
    # spaces the starts of the two requests (2026-10-27), so the wait is
    # what is left of it once the first has started; the spacing itself is
    # measured in `test_parallel.py`.
    assert len(slept) == 1
    assert 0 < slept[0] <= 0.5


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

    # Every wait recorded belongs to the crawl itself, not to the write
    # loop - and the crawl waits between its requests, not after the last.
    assert docs.contents().documents
    assert len(slept) == len(docs.contents().documents) - 1


def test_a_site_asking_for_a_longer_crawl_delay_is_paced_by_it(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """robots.txt was read for what it allows but not for how fast: a site
    asking for two seconds between requests got one every fifth of one."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5),
        client=sphinx_site("User-agent: *\nCrawl-delay: 2\nAllow: /\n"),
    )

    assert slept == [2.0]


def test_a_crawl_delay_is_honoured_only_up_to_a_bound(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """An hour between pages would be an add that never visibly ends."""
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5),
        client=sphinx_site("User-agent: *\nCrawl-delay: 3600\nAllow: /\n"),
    )

    assert slept == [30.0]


def test_a_site_already_held_is_not_paced_again(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """Every page is held, so none is asked for - and a re-crawl still slept
    before each one, which a pack sync of a large sitemap paid in full."""
    options = AddOptions(project="example", request_delay_seconds=0.5)
    add_docs(docs, [BASE], options, client=sphinx_site())
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(docs, [BASE], options, client=sphinx_site())

    assert slept == []


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


# ---------------------------------------------------------------------------
# A site that yielded nothing
# ---------------------------------------------------------------------------


def empty_site() -> httpx.Client:
    """A site that answers, and publishes no page under the prefix asked for.

    The real case this stands for: `docs.astropy.org/en/stable/io/fits/
    index.html` makes discovery derive the prefix `/en/stable/io/fits/` and
    settle on sitemap mode, and the sitemap lists nothing beneath it. The
    site root finds 1433 pages, so the difference between working and not is
    which URL was given - and the output was identical either way.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if path.endswith("searchindex.js"):
            return httpx.Response(404)
        if path.endswith("documentation_options.js"):
            return httpx.Response(404)
        if path.endswith("sitemap.xml"):
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><urlset></urlset>',
                headers={"content-type": "application/xml"},
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_site_with_no_pages_says_so(docs: Collection):
    """Found by running the command while writing the README.

    `Added 0 documents in 864ms`, exit 0, and nothing else. A person cannot
    tell from that whether the site has no pages, the prefix excluded all of
    them, the probe chose the wrong mode, or the fetch failed - and the four
    have different answers.
    """
    events = Recorder()

    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=empty_site(),
        events=events,
    )

    assert report.outcomes == []
    warnings = [
        event
        for event in events.events
        if isinstance(event, Diagnostic) and event.severity is Severity.WARNING
    ]
    assert warnings, "a site that produced nothing said nothing about it"
    detail = warnings[0].detail
    assert isinstance(detail, NoPagesDiscovered)
    assert detail.base_url == BASE


def test_the_warning_names_the_mode_and_the_prefix(docs: Collection):
    """The two facts that explain it. The prefix is derived rather than
    given, so it is the surprising half of the answer, and the mode is what
    decides whether a different URL would have worked."""
    events = Recorder()

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=empty_site(),
        events=events,
    )

    detail = next(
        event.detail
        for event in events.events
        if isinstance(event, Diagnostic) and event.severity is Severity.WARNING
    )
    assert isinstance(detail, NoPagesDiscovered)
    assert detail.mode == "sitemap"
    assert detail.path_prefix is not None
    assert "/en/latest/" in detail.path_prefix


def test_a_site_that_yielded_pages_warns_about_nothing(docs: Collection):
    """The control. A warning on every successful add would be noise, and
    noise is what stops a real one being read."""
    events = Recorder()

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
        events=events,
    )

    assert not [
        event
        for event in events.events
        if isinstance(event, Diagnostic) and event.severity is Severity.WARNING
    ]


def test_the_progress_bar_advances_once_per_page(docs: Collection):
    """Brian, on first use: the bar "did not move at all".

    `add_docs` emitted one `Progress` before the loop, at `completed=0`, and
    the loop emitted only `ItemStarted` and `ItemFinished` - which the
    display sink deliberately ignores. So the bar opened at 0 of 20 and sat
    there for sixty-nine seconds.
    """
    events = Recorder()

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
        events=events,
    )

    reached = [
        event.completed for event in events.events if isinstance(event, Progress)
    ]
    assert reached == [0, 1, 2], reached


def test_the_progress_bar_knows_the_total_before_it_starts(docs: Collection):
    """The first `Progress` is what opens the bar, and a bar opened without a
    total shows a spinner rather than a proportion. Discovery already knows
    how many pages there are, so it is emitted before the first page."""
    events = Recorder()

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
        events=events,
    )

    first = next(event for event in events.events if isinstance(event, Progress))
    assert first.completed == 0
    assert first.total == 2


# ---------------------------------------------------------------------------
# Pages fetched together (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def site_counting(
    robots: str, *, together: threading.Barrier | None = None
) -> tuple[httpx.Client, list[int]]:
    """`sphinx_site`, whose page requests wait at `together` and record the
    most in flight at once."""
    inner = sphinx_site(robots)
    lock = threading.Lock()
    counts = [0, 0]  # in flight now, most at once

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith(".html"):
            return inner.send(request)
        with lock:
            counts[0] += 1
            counts[1] = max(counts[1], counts[0])
        if together is not None:
            together.wait()
        else:
            # A real pause the patched `time.sleep` cannot shorten.
            threading.Event().wait(0.02)
        with lock:
            counts[0] -= 1
        return inner.send(request)

    return httpx.Client(transport=httpx.MockTransport(handler)), counts


def test_the_pages_of_a_site_naming_no_crawl_delay_are_fetched_together(
    docs: Collection,
):
    """Each page's answer waits for the other's request, so a site fetched
    one page at a time fails the barrier rather than passing."""
    client, counts = site_counting(
        "User-agent: *\nAllow: /\n", together=threading.Barrier(2, timeout=5)
    )

    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=client,
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.ADDED] * 2
    assert sorted(pages_of(docs)) == ["guide/start", "index"]
    assert counts[1] == 2


def test_a_site_naming_a_crawl_delay_is_fetched_one_page_at_a_time(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )
    client, counts = site_counting("User-agent: *\nCrawl-delay: 2\nAllow: /\n")

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5),
        client=client,
    )

    assert counts[1] == 1
    assert slept == [2.0]


def test_a_refresh_asks_for_the_pages_together(docs: Collection):
    options = AddOptions(project="example", request_delay_seconds=0)
    add_docs(docs, [BASE], options, client=sphinx_site())
    client, _ = site_counting(
        "User-agent: *\nAllow: /\n", together=threading.Barrier(2, timeout=5)
    )

    report = add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0, refresh=True),
        client=client,
    )

    assert [outcome.outcome for outcome in report.outcomes] == [Outcome.UNCHANGED] * 2


def test_progress_advances_as_the_pages_arrive(docs: Collection):
    recorder = Recorder()

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(),
        events=recorder,
    )

    progress = [
        (event.completed, event.total)
        for event in recorder.events
        if isinstance(event, Progress)
    ]
    assert progress == [(0, 2), (1, 2), (2, 2)]


def test_a_crawled_site_naming_a_crawl_delay_is_crawled_one_page_at_a_time(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """A site with neither a sitemap nor a Sphinx index is crawled; when its
    robots.txt asks for a delay, discovery must tell the crawl so."""
    monkeypatch.setattr("kennis.engine.corpus.add.time.sleep", lambda seconds: None)
    lock = threading.Lock()
    counts = [0, 0]
    linked = a_page("Overview").replace(
        "</div>", '<a href="one.html">1</a><a href="two.html">2</a></div>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 2\nAllow: /\n")
        if path.endswith(("searchindex.js", "sitemap.xml")):
            return httpx.Response(404)
        with lock:
            counts[0] += 1
            counts[1] = max(counts[1], counts[0])
        threading.Event().wait(0.02)
        with lock:
            counts[0] -= 1
        html = linked if path.endswith("/latest/") else a_page(path)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    add_docs(
        docs,
        [BASE],
        AddOptions(project="example", request_delay_seconds=0.5, max_depth=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert len(docs.contents().documents) == 3
    assert counts[1] == 1
