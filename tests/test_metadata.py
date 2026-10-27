"""arXiv's Atom API: the only part of literature that fetches.

Every network failure degrades to "identifier known, metadata not". The
identifier is what prevents the same paper landing twice and it is already in
hand by then; refusing to add a document because arXiv was unreachable would
trade a small loss for a total one.
"""

from __future__ import annotations

import re

import httpx

from kennis.engine.literature.citekeys import derive_citekey
from kennis.engine.literature.metadata import (
    PaperMetadata,
    lookup_arxiv_metadata,
    lookup_doi_metadata,
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

    assert any("id_list=2409.19750" in str(url) for url in seen)


ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_ph/0601234</id>
    <title>Error</title>
    <summary>incorrect id format for ph/0601234</summary>
    <author><name>arXiv api core</name></author>
  </entry>
</feed>
"""


def test_arxiv_s_error_entry_is_not_a_paper():
    """arXiv answers a malformed id with HTTP 200 and an entry titled
    "Error" by "arXiv api core"; it was written as the paper's metadata,
    with the citekey `coreError`."""
    assert (
        lookup_arxiv_metadata("ph/0601234", client=client_returning(ERROR_FEED)) is None
    )


def test_an_entry_for_another_paper_is_not_this_one():
    assert lookup_arxiv_metadata("2410.00001", client=client_returning(ENTRY)) is None


def test_a_versioned_request_still_matches_its_entry():
    assert lookup_arxiv_metadata("2409.19750v1", client=client_returning(ENTRY))


# ---------------------------------------------------------------------------
# The abs page, when the Atom API fails (#288)
# ---------------------------------------------------------------------------

# As arxiv.org served `1101.1764` on 2026-10-18, cut to the tags read, one
# author added so the order is tested, and the title given an entity. The
# revision is moved into the next year, so a year read from the wrong date
# is seen (#352: in the real page both dates are in 2011).
ABS_PAGE = """<html><head>
<meta name="citation_title" content="Revisiting the radio interferometer
  measurement equation. I. A full-sky Jones formalism &amp; more" />
<meta name="citation_author" content="Smirnov, Oleg M." />
<meta name="citation_author" content="Welman, Brian" />
<meta name="citation_doi" content="10.1051/0004-6361/201016082" />
<meta name="citation_date" content="2011/01/10" />
<meta name="citation_online_date" content="2012/02/04" />
<meta name="citation_arxiv_id" content="1101.1764" />
</head><body></body></html>
"""


def arxiv_with(
    *, atom_status: int, abs_page: str = ABS_PAGE, abs_status: int = 200
) -> tuple[httpx.Client, list[str]]:
    """The Atom API answering `atom_status`, and arxiv.org serving
    `abs_page`; with every request's host and path recorded but the
    robots files, which `test_courtesy.py` is about."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/robots.txt":
            asked.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "export.arxiv.org":
            return httpx.Response(atom_status, text=ENTRY)
        return httpx.Response(
            abs_status, text=abs_page, headers={"content-type": "text/html"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def test_a_refused_api_is_answered_from_the_abs_page():
    client, asked = arxiv_with(atom_status=406)

    metadata = lookup_arxiv_metadata("1101.1764", client=client)

    assert metadata is not None
    assert metadata.title == (
        "Revisiting the radio interferometer measurement equation. "
        "I. A full-sky Jones formalism & more"
    )
    assert metadata.authors == "Smirnov, Oleg M. and Welman, Brian"
    assert metadata.year == "2011"
    assert asked == ["export.arxiv.org/api/query", "arxiv.org/abs/1101.1764"]


def test_an_answering_api_is_not_followed_by_the_abs_page():
    client, asked = arxiv_with(atom_status=200)

    lookup_arxiv_metadata("2409.19750", client=client)

    assert asked == ["export.arxiv.org/api/query"]


def test_an_old_style_identifier_reaches_its_abs_page():
    page = ABS_PAGE.replace('content="1101.1764"', 'content="astro-ph/0207156"')
    client, asked = arxiv_with(atom_status=406, abs_page=page)

    metadata = lookup_arxiv_metadata("astro-ph/0207156", client=client)

    assert metadata is not None
    assert asked[-1] == "arxiv.org/abs/astro-ph/0207156"


def test_an_abs_page_for_another_paper_is_not_this_one():
    page = ABS_PAGE.replace('content="1101.1764"', 'content="1101.9999"')
    client, _ = arxiv_with(atom_status=406, abs_page=page)

    assert lookup_arxiv_metadata("1101.1764", client=client) is None


def test_a_versioned_request_matches_its_abs_page():
    client, _ = arxiv_with(atom_status=406)

    assert lookup_arxiv_metadata("1101.1764v2", client=client) is not None


def test_an_abs_page_without_a_title_is_nothing():
    page = re.sub(r'<meta name="citation_title"[^>]*/>', "", ABS_PAGE, flags=re.S)
    client, _ = arxiv_with(atom_status=406, abs_page=page)

    assert lookup_arxiv_metadata("1101.1764", client=client) is None


def test_a_missing_abs_page_is_nothing_rather_than_an_error():
    client, _ = arxiv_with(atom_status=406, abs_status=404)

    assert lookup_arxiv_metadata("1101.1764", client=client) is None


def test_an_unreachable_arxiv_is_still_nothing_rather_than_an_error():
    assert lookup_arxiv_metadata("1101.1764", client=client_that_fails()) is None


def test_the_abs_page_s_authors_give_the_same_citekey_as_the_api_s():
    """arXiv writes `Surname, Given` on the page and `Given Surname` in the
    feed; a paper's citekey must not depend on which one answered."""
    client, _ = arxiv_with(atom_status=406)
    metadata = lookup_arxiv_metadata("1101.1764", client=client)
    assert metadata is not None

    from_page = derive_citekey(
        authors=metadata.authors, year=metadata.year, title=metadata.title
    )
    from_feed = derive_citekey(
        authors="Oleg M. Smirnov and Brian Welman",
        year=metadata.year,
        title=metadata.title,
    )

    assert from_page == from_feed


def test_a_response_that_is_not_a_page_is_nothing():
    """The abs address answering with anything but HTML is not the page."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "export.arxiv.org":
            return httpx.Response(406)
        return httpx.Response(
            200, text=ABS_PAGE, headers={"content-type": "application/xml"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert lookup_arxiv_metadata("1101.1764", client=client) is None


# ---------------------------------------------------------------------------
# A DOI, described by its registry (Brian, 2026-10-26)
# ---------------------------------------------------------------------------

# The shapes doi.org's content negotiation answered on 2026-10-26: Crossref
# gives print and online dates, DataCite only `issued`.
CROSSREF_CSL = {
    "DOI": "10.1017/pasa.2025.10128",
    "title": "The Dawes review 13: A new look at the dynamic radio sky",
    "author": [
        {"family": "Murphy", "given": "Tara"},
        {"family": "Kaplan", "given": "David L."},
    ],
    "issued": {"date-parts": [[2025, 12, 2]]},
    "published-print": {"date-parts": [[2026]]},
}
DATACITE_CSL = {
    "DOI": "10.48479/BHPJ-NZ95",
    "title": "RFI at u=0 in MeerKAT observations",
    "author": [{"family": "Maccagni", "given": "Filippo Marcello"}],
    "issued": {"date-parts": [[2022]]},
}


def registry(
    answer: object, status: int = 200, seen: list[httpx.Request] | None = None
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if seen is not None:
            seen.append(request)
        if isinstance(answer, str):
            return httpx.Response(status, text=answer)
        return httpx.Response(
            status,
            json=answer,
            headers={"content-type": "application/vnd.citationstyles.csl+json"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_doi_is_described_by_its_registry_through_doi_org():
    seen: list[httpx.Request] = []

    metadata = lookup_doi_metadata(
        "10.1017/pasa.2025.10128", client=registry(CROSSREF_CSL, seen=seen)
    )

    assert metadata == PaperMetadata(
        title="The Dawes review 13: A new look at the dynamic radio sky",
        authors="Murphy, Tara and Kaplan, David L.",
        year="2026",
    )
    [request] = seen
    assert str(request.url) == "https://doi.org/10.1017/pasa.2025.10128"
    assert request.headers["accept"] == "application/vnd.citationstyles.csl+json"


def test_the_year_is_the_issue_s_and_else_when_it_was_issued():
    metadata = lookup_doi_metadata("10.48479/bhpj-nz95", client=registry(DATACITE_CSL))

    assert metadata is not None
    assert metadata.year == "2022"


def test_a_registry_s_citekey_is_the_one_its_authors_and_year_give():
    metadata = lookup_doi_metadata(
        "10.1017/pasa.2025.10128", client=registry(CROSSREF_CSL)
    )

    assert metadata is not None
    citekey = derive_citekey(
        authors=metadata.authors, year=metadata.year, title=metadata.title
    )
    assert citekey.startswith("murphy") and citekey.endswith("2026")


def test_a_collaboration_is_named_as_the_registry_writes_it():
    answer = {
        **DATACITE_CSL,
        "title": ["A title given as a list", "A subtitle"],
        "author": [{"literal": "MeerKAT Collaboration"}, {"family": "Healy"}],
    }

    metadata = lookup_doi_metadata("10.48479/bhpj-nz95", client=registry(answer))

    assert metadata is not None
    assert metadata.title == "A title given as a list"
    assert metadata.authors == "MeerKAT Collaboration and Healy"


def test_an_answer_for_another_doi_is_not_this_paper():
    assert (
        lookup_doi_metadata("10.1093/mnrasl/slaf009", client=registry(CROSSREF_CSL))
        is None
    )


def test_a_doi_the_registry_cannot_describe_is_nothing_rather_than_an_error():
    untitled = {key: value for key, value in CROSSREF_CSL.items() if key != "title"}

    assert lookup_doi_metadata("10.1/x", client=registry({}, status=404)) is None
    assert (
        lookup_doi_metadata("10.1/x", client=registry("<html>not json</html>")) is None
    )
    assert lookup_doi_metadata("10.1/x", client=registry(["a", "list"])) is None
    assert (
        lookup_doi_metadata("10.1017/pasa.2025.10128", client=registry(untitled))
        is None
    )
    assert lookup_doi_metadata("10.1/x", client=client_that_fails()) is None


def test_a_no_break_space_inside_a_name_is_an_ordinary_space():
    """Crossref sends `de\\u00a0Blok` and `S \\u00a0J`, measured on
    10.1093/mnras/stae382 and 10.1093/mnrasl/slaf009 on 2026-10-26."""
    answer = {
        **CROSSREF_CSL,
        "author": [
            {"family": "de\u00a0Blok", "given": "W J G"},
            {"family": "Perkins", "given": "S \u00a0J"},
        ],
    }

    metadata = lookup_doi_metadata("10.1017/pasa.2025.10128", client=registry(answer))

    assert metadata is not None
    assert metadata.authors == "de Blok, W J G and Perkins, S J"
