"""Asking a host only what its robots.txt allows, as often as it asks.

**One place keeps every host's rules for the process.** A `corpus add` of
twenty papers asks arXiv forty times; reading `robots.txt` before each would
double that, and pacing by a figure written into kennis ignores what the
host itself says. So each origin's file is read once (and again after a day,
RFC 9309's ceiling on caching it), a path it disallows is never requested,
and requests to one origin are spaced by its `Crawl-delay`.

Measured 2026-10-18 and the reason this exists (#492): `arxiv.org` asks for
fifteen seconds between requests, and `export.arxiv.org`, the Atom API,
disallows everything. Neither figure is written here; both are read.

**Process-wide state, deliberately.** The window runs jobs and previews on
threads of one process, and a host does not care which of them is asking.
A host whose robots.txt names a `Crawl-delay` is asked one request at a
time: one lock holds the wait and the request together, so two threads
cannot both decide the host is free. A host that names none is asked up to
`PARALLEL_REQUESTS` at once (Brian, 2026-10-27), which is what lets a run
of DOI lookups wait for Crossref once rather than once each. A test clears
the hosts with `forget_hosts`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Final
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from kennis.engine.bounded import get_bounded
from kennis.engine.parallel import PARALLEL_REQUESTS

# The longest `Crawl-delay` honoured. A host asking for more is still read,
# this slowly: a minute a request looks no different from a hung add.
MAX_CRAWL_DELAY_SECONDS: Final = 30.0

# RFC 9309: a crawler should not use a cached robots.txt for more than a day.
_RULES_LIFETIME_SECONDS: Final = 24 * 60 * 60

# The two answers a missing or refused robots.txt stands for, written as
# robots bodies rather than set on the parser's `allow_all`/`disallow_all`
# attributes: those exist at runtime but are not part of the declared
# interface, and parsing an equivalent body is the same behaviour through the
# documented one. An empty body matches nothing, so everything is allowed.
_ALLOW_EVERYTHING: Final = ()
_FORBID_EVERYTHING: Final = ("User-agent: *", "Disallow: /")


class Disallowed(httpx.RequestError):
    """A request the host's robots.txt does not allow.

    An `httpx.HTTPError`, so every caller that already treats a failed
    request as "this source is unavailable" treats this one the same way.
    """


@dataclass(slots=True)
class _Host:
    rules: RobotFileParser
    read_at: float
    # When this origin was last asked anything, robots.txt included.
    last_request: float
    # Guards the rules and the turn; held across a request only while the
    # host asks for a delay, as `one_at_a_time`.
    lock: threading.Lock
    several: threading.BoundedSemaphore


_hosts: dict[str, _Host] = {}
_hosts_lock = threading.Lock()


def robots_for(client: httpx.Client, origin: str) -> RobotFileParser:
    """`{origin}/robots.txt`, parsed.

    Fetched through the caller's own client rather than through
    `urllib.robotparser`'s `urlopen`, which means replicating by hand the
    status handling it would have done: refusing to serve robots.txt at all
    (401 or 403) forbids everything, any other client error allows
    everything, and an unreachable file is absent rather than forbidding.
    """
    return _rules_of(client, origin)[0]


def _rules_of(client: httpx.Client, origin: str) -> tuple[RobotFileParser, bool]:
    """The parsed rules, and whether they may be kept for a day.

    Not when they stand for a server error or an unreachable file: that is
    the host's state now, and held for a day by a window that stays open
    it would stop kennis asking arXiv for a day after a minute's outage.
    """
    # Here rather than at the top: importing the docs package runs its
    # `__init__`, whose crawler imports this module.
    from kennis.engine.docs.http import get_within

    parser = RobotFileParser()
    robots_url = urljoin(origin + "/", "robots.txt")
    parser.set_url(robots_url)
    try:
        response = get_within(client, robots_url, origin=origin)
    except httpx.HTTPError:
        parser.parse(_ALLOW_EVERYTHING)
        return parser, False

    # A server error is "may not crawl now", as RFC 9309 has it: its body
    # is an error page, and parsed as rules it allowed everything.
    if response.status_code in (401, 403) or response.status_code >= 500:
        parser.parse(_FORBID_EVERYTHING)
    elif 400 <= response.status_code < 500:
        parser.parse(_ALLOW_EVERYTHING)
    else:
        parser.parse(response.text.splitlines())
    return parser, response.status_code < 500


def crawl_delay(rules: RobotFileParser, user_agent: str) -> float:
    """The host's `Crawl-delay` for this agent, capped; 0 when it names none."""
    asked = rules.crawl_delay(user_agent)
    if asked is None:
        return 0.0
    return min(float(asked), MAX_CRAWL_DELAY_SECONDS)


def get_politely(
    client: httpx.Client,
    url: str,
    *,
    user_agent: str,
    timeout: float,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool | None = None,
) -> httpx.Response:
    """GET `url` if its host's robots.txt allows it, once its delay has passed.

    Raises `Disallowed` without asking when the rules forbid the path. The
    query string is part of what the rules are matched against, as a
    crawler's would be.
    """
    origin = _origin_of(url)
    host = _host_for(client, origin)
    target = url if not params else str(httpx.URL(url, params=params))
    with host.lock:
        allowed = host.rules.can_fetch(user_agent, target)
        delay = crawl_delay(host.rules, user_agent)
    if not allowed:
        raise Disallowed(f"{origin}'s robots.txt does not allow '{url}'")
    with host.lock if delay else host.several:
        _wait_turn(host, delay)
        try:
            return get_bounded(
                client,
                url,
                timeout=timeout,
                params=params,
                headers=headers,
                follow_redirects=follow_redirects,
            )
        finally:
            host.last_request = monotonic()


def forget_hosts() -> None:
    """Drop every host's rules and timing. For a test, which must not
    inherit the last test's hosts."""
    with _hosts_lock:
        _hosts.clear()


def _host_for(client: httpx.Client, origin: str) -> _Host:
    """This origin's record, reading its robots.txt when there is none
    or the one held is more than a day old."""
    with _hosts_lock:
        host = _hosts.get(origin)
        if host is None:
            host = _Host(
                rules=RobotFileParser(),
                read_at=-_RULES_LIFETIME_SECONDS,
                last_request=-MAX_CRAWL_DELAY_SECONDS,
                lock=threading.Lock(),
                several=threading.BoundedSemaphore(PARALLEL_REQUESTS),
            )
            _hosts[origin] = host
    with host.lock:
        if monotonic() - host.read_at >= _RULES_LIFETIME_SECONDS:
            host.rules, lasting = _rules_of(client, origin)
            host.last_request = monotonic()
            # Rules that may not be kept are read again on the next request.
            host.read_at = host.last_request if lasting else -_RULES_LIFETIME_SECONDS
    return host


def _wait_turn(host: _Host, delay: float) -> None:
    remaining = host.last_request + delay - monotonic()
    if remaining > 0:
        sleep(remaining)


def _origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


__all__ = [
    "MAX_CRAWL_DELAY_SECONDS",
    "Disallowed",
    "crawl_delay",
    "forget_hosts",
    "get_politely",
    "robots_for",
]
