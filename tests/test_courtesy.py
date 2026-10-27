"""A host is asked only what its robots.txt allows, as often as it asks (#492).

`engine/courtesy.py` keeps each origin's rules for the process: a path the
rules disallow is never requested, and requests to one origin are spaced by
its `Crawl-delay`. arXiv's own files are why: `arxiv.org` asks for fifteen
seconds between requests and `export.arxiv.org` disallows everything.

The clock is the module's own, replaced here, so nothing sleeps.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from kennis.engine import courtesy
from kennis.engine.courtesy import Disallowed, get_politely
from kennis.engine.literature.fetch import fetch_paper
from kennis.engine.literature.metadata import lookup_arxiv_metadata
from kennis.engine.parallel import PARALLEL_REQUESTS

AGENT = "kennis-test"


class Clock:
    """Monotonic time that moves only when slept through or advanced."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(courtesy, "monotonic", fake.monotonic)
    monkeypatch.setattr(courtesy, "sleep", fake.sleep)
    return fake


def serving(
    robots: str | None, asked: list[str], *, robots_status: int = 200
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == "/robots.txt":
            if robots is None:
                return httpx.Response(404)
            return httpx.Response(robots_status, text=robots)
        return httpx.Response(200, text="<html>page</html>")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_disallowed_path_is_never_requested(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nDisallow: /\n", asked)

    with pytest.raises(Disallowed):
        get_politely(
            client, "https://export.example.org/api/query", user_agent=AGENT, timeout=5
        )

    assert asked == ["/robots.txt"]


def test_a_disallowed_request_is_an_httpx_error_so_callers_treat_it_as_unavailable():
    assert issubclass(Disallowed, httpx.HTTPError)


def test_requests_to_one_host_are_spaced_by_its_crawl_delay(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nCrawl-delay: 15\n", asked)

    get_politely(client, "https://arxiv.example.org/abs/1", user_agent=AGENT, timeout=5)
    get_politely(client, "https://arxiv.example.org/abs/2", user_agent=AGENT, timeout=5)

    assert asked == ["/robots.txt", "/abs/1", "/abs/2"]
    # The robots file is a request too: the first page waits for it.
    assert clock.slept == [15.0, 15.0]


def test_time_already_passed_is_not_waited_again(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nCrawl-delay: 15\n", asked)
    get_politely(client, "https://arxiv.example.org/abs/1", user_agent=AGENT, timeout=5)
    clock.slept.clear()
    clock.now += 10

    get_politely(client, "https://arxiv.example.org/abs/2", user_agent=AGENT, timeout=5)

    assert clock.slept == [5.0]


def test_the_rules_are_read_once_per_host(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nAllow: /\n", asked)

    for number in range(3):
        get_politely(
            client,
            f"https://arxiv.example.org/abs/{number}",
            user_agent=AGENT,
            timeout=5,
        )

    assert asked.count("/robots.txt") == 1


def test_one_hosts_delay_does_not_hold_up_another(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nCrawl-delay: 15\n", asked)
    get_politely(client, "https://one.example.org/a", user_agent=AGENT, timeout=5)
    clock.slept.clear()

    get_politely(
        client, "https://two.example.org/robots-free", user_agent=AGENT, timeout=5
    )

    # Only the second host's own robots file is waited for.
    assert clock.slept == [15.0]


def test_a_very_long_crawl_delay_is_capped(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nCrawl-delay: 600\n", asked)

    get_politely(client, "https://slow.example.org/a", user_agent=AGENT, timeout=5)

    assert clock.slept == [courtesy.MAX_CRAWL_DELAY_SECONDS]


def test_a_host_with_no_robots_file_is_asked_without_waiting(clock: Clock):
    asked: list[str] = []
    client = serving(None, asked)

    get_politely(client, "https://plain.example.org/a", user_agent=AGENT, timeout=5)
    get_politely(client, "https://plain.example.org/b", user_agent=AGENT, timeout=5)

    assert asked == ["/robots.txt", "/a", "/b"]
    assert clock.slept == []


def test_a_refused_robots_file_forbids_everything(clock: Clock):
    asked: list[str] = []
    client = serving("anything", asked, robots_status=403)

    with pytest.raises(Disallowed):
        get_politely(
            client, "https://closed.example.org/a", user_agent=AGENT, timeout=5
        )


def test_the_rules_for_this_agent_are_the_ones_applied(clock: Clock):
    asked: list[str] = []
    client = serving(
        "User-agent: kennis-test\nDisallow: /private\n\nUser-agent: *\nAllow: /\n",
        asked,
    )

    with pytest.raises(Disallowed):
        get_politely(
            client, "https://mixed.example.org/private/a", user_agent=AGENT, timeout=5
        )
    get_politely(
        client, "https://mixed.example.org/public", user_agent=AGENT, timeout=5
    )

    assert asked == ["/robots.txt", "/public"]


# ---------------------------------------------------------------------------
# arXiv, as its files read on 2026-10-18
# ---------------------------------------------------------------------------

ARXIV_ROBOTS = "User-agent: *\nCrawl-delay: 15\nAllow: /abs\nAllow: /html\n"
EXPORT_ROBOTS = "User-agent: * \nDisallow: /\n"
ABS_PAGE = (
    "<html><head>"
    '<meta name="citation_title" content="Revisiting the RIME" />'
    '<meta name="citation_author" content="Smirnov, Oleg M." />'
    '<meta name="citation_date" content="2011/01/10" />'
    '<meta name="citation_arxiv_id" content="1101.1764" />'
    "</head><body></body></html>"
)


def arxiv(asked: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        host, path = request.url.host, request.url.path
        if path == "/robots.txt":
            body = EXPORT_ROBOTS if host == "export.arxiv.org" else ARXIV_ROBOTS
            return httpx.Response(200, text=body)
        if host == "export.arxiv.org":
            raise AssertionError(
                "the Atom API was asked although its robots.txt forbids it"
            )
        if path.startswith("/abs/"):
            return httpx.Response(
                200, text=ABS_PAGE, headers={"content-type": "text/html"}
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_arxiv_metadata_comes_from_the_abs_page_and_never_the_api(clock: Clock):
    asked: list[str] = []

    found = lookup_arxiv_metadata("1101.1764", client=arxiv(asked))

    assert found is not None and found.title == "Revisiting the RIME"
    assert not any("/api/" in url for url in asked)
    assert "https://export.arxiv.org/robots.txt" in asked


def test_arxiv_requests_are_fifteen_seconds_apart(clock: Clock):
    asked: list[str] = []
    client = arxiv(asked)

    lookup_arxiv_metadata("1101.1764", client=client)
    fetch_paper("1101.1764", client=client)

    on_arxiv = [url for url in asked if url.startswith("https://arxiv.org/")]
    assert on_arxiv[:3] == [
        "https://arxiv.org/robots.txt",
        "https://arxiv.org/abs/1101.1764",
        "https://arxiv.org/html/1101.1764",
    ]
    assert clock.slept.count(15.0) >= 2


def test_a_server_error_on_robots_is_asked_again_next_time(clock: Clock):
    """It forbids for now, not for a day: the window stays open for days."""
    asked: list[str] = []
    client = serving("anything", asked, robots_status=503)
    with pytest.raises(Disallowed):
        get_politely(client, "https://down.example.org/a", user_agent=AGENT, timeout=5)

    with pytest.raises(Disallowed):
        get_politely(client, "https://down.example.org/a", user_agent=AGENT, timeout=5)

    assert asked == ["/robots.txt", "/robots.txt"]


def test_rules_are_read_again_after_a_day(clock: Clock):
    asked: list[str] = []
    client = serving("User-agent: *\nAllow: /\n", asked)
    get_politely(client, "https://daily.example.org/a", user_agent=AGENT, timeout=5)
    clock.now += 24 * 60 * 60

    get_politely(client, "https://daily.example.org/b", user_agent=AGENT, timeout=5)

    assert asked == ["/robots.txt", "/a", "/robots.txt", "/b"]


# ---------------------------------------------------------------------------
# Several at once, where the host asks for no delay (2026-10-27)
# ---------------------------------------------------------------------------


def asked_from_threads(client: httpx.Client, paths: list[str]) -> list[int]:
    """Each path asked of one origin from its own thread; the statuses."""
    statuses: list[int] = []
    lock = threading.Lock()

    def ask(path: str) -> None:
        response = get_politely(
            client, f"https://registry.example.org{path}", user_agent=AGENT, timeout=5
        )
        with lock:
            statuses.append(response.status_code)

    threads = [threading.Thread(target=ask, args=(path,)) for path in paths]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return statuses


def test_a_host_naming_no_crawl_delay_is_asked_several_at_once():
    """doi.org's robots.txt is empty, and a lookup is Crossref's 1 to 10 s.
    Each request waits for the other to be in flight, so a host asked one
    at a time fails the barrier rather than passing."""
    together = threading.Barrier(2, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        together.wait()
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert asked_from_threads(client, ["/a", "/b"]) == [200, 200]


def test_a_host_naming_a_crawl_delay_is_asked_one_at_a_time(clock: Clock):
    """arXiv asks for fifteen seconds between requests; parallel callers
    must not turn that into several requests every fifteen seconds."""
    lock = threading.Lock()
    in_flight = 0
    most = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, most
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 15\n")
        with lock:
            in_flight += 1
            most = max(most, in_flight)
        time.sleep(0.02)
        with lock:
            in_flight -= 1
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert asked_from_threads(client, ["/a", "/b", "/c"]) == [200, 200, 200]
    assert most == 1
    assert clock.slept == [15.0, 15.0, 15.0]


def test_no_more_than_the_parallel_requests_are_in_flight_to_one_host():
    """Every request is held until the test lets them go. Once
    `PARALLEL_REQUESTS` are in flight, a fifth must not start: the test
    gives one a moment to, since an absence cannot be waited for, and a
    host with no limit has all eight in flight long before then."""
    changed = threading.Condition()
    in_flight = 0
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        with changed:
            in_flight += 1
            changed.notify_all()
        assert release.wait(10)
        with changed:
            in_flight -= 1
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    paths = [f"/{number}" for number in range(PARALLEL_REQUESTS * 2)]
    asking = threading.Thread(target=asked_from_threads, args=(client, paths))
    asking.start()
    try:
        with changed:
            assert changed.wait_for(lambda: in_flight == PARALLEL_REQUESTS, 5)
            assert not changed.wait_for(lambda: in_flight > PARALLEL_REQUESTS, 0.2)
    finally:
        release.set()
        asking.join(timeout=10)
