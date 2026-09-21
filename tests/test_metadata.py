"""arXiv's Atom API: the only part of literature that fetches.

Every network failure degrades to "identifier known, metadata not". The
identifier is what prevents the same paper landing twice and it is already in
hand by then; refusing to add a document because arXiv was unreachable would
trade a small loss for a total one.
"""

from __future__ import annotations

import httpx

from kennis.engine.literature.metadata import (
    lookup_arxiv_metadata,
    resolve_doi_to_arxiv,
)

ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2409.19750v1</id>
    <published>2024-09-29T12:00:00Z</published>
    <title>A Paper About
      Calibration</title>
    <author><name>Brian Welman</name></author>
    <author><name>Oleg Smirnov</name></author>
  </entry>
</feed>
"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def client_returning(body: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def client_that_fails() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_an_arxiv_identifier_is_enough_to_learn_what_a_paper_is():
    """What upgrades a citekey from `paperRadioInterferometry` to
    `welmanPaperAbout2024`."""
    metadata = lookup_arxiv_metadata("2409.19750", client=client_returning(ENTRY))

    assert metadata is not None
    assert metadata.title == "A Paper About Calibration"
    assert metadata.authors == "Brian Welman and Oleg Smirnov"
    assert metadata.year == "2024"


def test_a_title_broken_across_lines_is_put_back_together():
    """arXiv wraps long titles in its Atom output."""
    metadata = lookup_arxiv_metadata("2409.19750", client=client_returning(ENTRY))

    assert metadata is not None
    assert "\n" not in metadata.title


def test_a_paper_arxiv_does_not_hold_yields_nothing():
    assert (
        lookup_arxiv_metadata("9999.99999", client=client_returning(EMPTY_FEED)) is None
    )


def test_an_unreachable_arxiv_degrades_rather_than_raising():
    """The identifier is already in hand; refusing the document because the
    network was down would trade a small loss for a total one."""
    assert lookup_arxiv_metadata("2409.19750", client=client_that_fails()) is None


def test_an_error_response_degrades_too():
    assert lookup_arxiv_metadata("2409.19750", client=client_returning("", 503)) is None


def test_a_response_that_is_not_xml_degrades_too():
    assert (
        lookup_arxiv_metadata("2409.19750", client=client_returning("<not xml at all"))
        is None
    )


# ---------------------------------------------------------------------------
# DOI to preprint
# ---------------------------------------------------------------------------


def test_a_doi_may_reach_a_preprint():
    """Many arXiv records carry the published version's DOI, so a DOI is often
    enough to reach a fetchable preprint."""
    assert (
        resolve_doi_to_arxiv("10.1088/0004-637X/1", client=client_returning(ENTRY))
        == "2409.19750"
    )


def test_a_doi_with_no_preprint_is_a_miss_not_an_error():
    """The paper may simply never have been preprinted, which the caller
    reports as needing a document supplied by hand instead."""
    assert (
        resolve_doi_to_arxiv("10.1088/x", client=client_returning(EMPTY_FEED)) is None
    )


def test_an_unreachable_arxiv_is_a_miss_here_too():
    assert resolve_doi_to_arxiv("10.1088/x", client=client_that_fails()) is None


# ---------------------------------------------------------------------------
# What is asked for
# ---------------------------------------------------------------------------


def recording_client() -> tuple[httpx.Client, list[httpx.URL]]:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, text=ENTRY)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_a_metadata_lookup_asks_for_one_identifier():
    client, seen = recording_client()

    lookup_arxiv_metadata("2409.19750", client=client)

    assert "id_list=2409.19750" in str(seen[0])


def test_a_doi_resolution_searches_rather_than_naming_an_identifier():
    client, seen = recording_client()

    resolve_doi_to_arxiv("10.1088/x", client=client)

    assert "search_query" in str(seen[0])
