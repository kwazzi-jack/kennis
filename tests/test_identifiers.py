"""Recognising the many ways a paper can be named.

Nothing here touches the network. The distinction that carries the most weight
is between searching a page for an identifier and matching one a user typed:
the first is right for a paper's own text and catastrophic for an argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.literature.identifiers import (
    PaperIdentifier,
    arxiv_id_if_reference,
    find_paper_identifiers,
    looks_like_bibtex,
    normalize_arxiv_id,
    normalize_bibcode,
    normalize_doi,
    parse_bibtex,
    parse_bibtex_file,
    parse_identifier,
)

# ---------------------------------------------------------------------------
# arXiv identifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "2409.19750",
        "2409.19750v1",
        "arXiv:2409.19750",
        "arxiv:2409.19750",
        "2409.19750v1.pdf",
        "https://arxiv.org/abs/2409.19750v1",
        "https://arxiv.org/pdf/2409.19750",
        "https://ar5iv.labs.arxiv.org/html/2409.19750",
    ],
)
def test_every_spelling_arxiv_hands_out_is_recognised(spelling: str):
    assert normalize_arxiv_id(spelling) == "2409.19750"


def test_the_pre_2007_form_is_recognised():
    assert normalize_arxiv_id("astro-ph/0601234") == "astro-ph/0601234"
    assert normalize_arxiv_id("arXiv:astro-ph/0601234v2") == "astro-ph/0601234"


def test_the_version_suffix_is_dropped():
    """The corpus tracks a paper, not a snapshot of one. Keeping the version
    would make v1 and v2 look like two documents to duplicate detection while
    fetching near-identical text twice."""
    assert normalize_arxiv_id("2409.19750v7") == "2409.19750"


def test_a_url_counts_only_when_the_host_is_arxivs():
    """An unrelated page whose path happens to contain digits must not be
    misread as a paper."""
    assert normalize_arxiv_id("https://example.org/reports/2409.19750") is None


@pytest.mark.parametrize("nothing", ["", "   ", "welman2024", "not a paper"])
def test_a_string_with_no_arxiv_identifier_yields_none(nothing: str):
    assert normalize_arxiv_id(nothing) is None


# ---------------------------------------------------------------------------
# Searching versus matching
# ---------------------------------------------------------------------------


def test_searching_finds_an_identifier_inside_a_longer_string():
    """Right when reading an identifier out of a paper's own page."""
    assert normalize_arxiv_id("see also arXiv:2409.19750 for the method") == (
        "2409.19750"
    )


def test_matching_refuses_an_identifier_merely_contained_in_an_argument():
    """Any filename carrying a date-shaped run of digits contains an arXiv
    identifier by the searching reading, and answering a mistyped path by
    silently fetching an unrelated paper is the worst failure here."""
    assert arxiv_id_if_reference("my-paper-2409.19750.md") is None
    assert normalize_arxiv_id("my-paper-2409.19750.md") == "2409.19750"


@pytest.mark.parametrize(
    "argument",
    ["2409.19750", "arXiv:2409.19750", "2409.19750v1", "2409.19750.pdf"],
)
def test_matching_accepts_the_spellings_arxiv_itself_hands_out(argument: str):
    assert arxiv_id_if_reference(argument) == "2409.19750"


def test_matching_still_takes_a_url_loosely():
    """`normalize_arxiv_id` already requires an arXiv-family host, so there is
    nothing looser about it."""
    assert arxiv_id_if_reference("https://arxiv.org/abs/2409.19750") == "2409.19750"


# ---------------------------------------------------------------------------
# DOIs and bibcodes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "10.1088/0004-637X/1",
        "doi:10.1088/0004-637X/1",
        "https://doi.org/10.1088/0004-637X/1",
        "10.1088/0004-637X/1.",
    ],
)
def test_a_doi_is_recognised_in_its_several_spellings(spelling: str):
    assert normalize_doi(spelling) == "10.1088/0004-637X/1"


def test_a_string_with_no_doi_yields_none():
    assert normalize_doi("2409.19750") is None


def test_a_bibcode_is_recognised():
    """The astronomy-native identifier, and the only one a pre-arXiv paper
    reliably has."""
    assert normalize_bibcode("1974A&AS...15..417H") == "1974A&AS...15..417H"


def test_a_bibcode_is_recorded_but_never_resolved():
    """Resolving one needs the ADS API and a key, which kennis does not ask
    anyone for. Its value here is identity: it gives a pre-arXiv paper
    something to be deduplicated on."""
    assert parse_identifier("1974A&AS...15..417H") == PaperIdentifier(
        kind="bibcode", value="1974A&AS...15..417H"
    )


def test_something_that_is_no_kind_of_identifier_is_none():
    assert parse_identifier("a paper about interferometry") is None


@pytest.mark.parametrize(
    ("argument", "kind"),
    [
        ("2409.19750", "arxiv"),
        ("10.1088/0004-637X/1", "doi"),
        ("1974A&AS...15..417H", "bibcode"),
    ],
)
def test_one_identifier_a_user_typed_is_classified(argument: str, kind: str):
    found = parse_identifier(argument)

    assert found is not None
    assert found.kind == kind


# ---------------------------------------------------------------------------
# Reading a front page
# ---------------------------------------------------------------------------


FRONT_PAGE = """arXiv:1805.03410v2 [astro-ph.IM] 14 Jun 2018

A Paper About Calibration

We build on the approach of arXiv:1101.1764 and the results in
10.1088/0004-637X/1, first reported as 1974A&AS...15..417H in the survey.
"""


def test_a_front_page_offers_every_identifier_it_carries():
    """kennis does not decide which of these names the document. It cannot: a
    first page carries the paper's own stamp and identifiers belonging to
    things it cites, and no pattern work distinguishes them."""
    found = find_paper_identifiers(FRONT_PAGE)

    assert [identifier.value for identifier in found] == [
        "1805.03410",
        "1101.1764",
        "10.1088/0004-637X/1",
        "1974A&AS...15..417H",
    ]


def test_candidates_are_ranked_by_kind_then_by_appearance():
    """arXiv first, then DOI, then bibcode - the order of how much each can be
    turned into. Within a kind, order of appearance, and since the caller
    hands page furniture over before body text, a margin stamp sorts above
    something in a paragraph."""
    kinds = [identifier.kind for identifier in find_paper_identifiers(FRONT_PAGE)]

    assert kinds == ["arxiv", "arxiv", "doi", "bibcode"]


def test_a_page_offering_nothing_offers_nothing():
    assert find_paper_identifiers("Just some prose about radio astronomy.") == []
    assert find_paper_identifiers("") == []


def test_the_same_identifier_twice_is_one_candidate():
    assert len(find_paper_identifiers("2409.19750 and again 2409.19750")) == 1


# ---------------------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------------------


BIBTEX = """@article{welman2024calibration,
  title = {A Paper About Calibration},
  author = {Welman, Brian and Smirnov, Oleg},
  year = {2024},
  doi = {10.1088/0004-637X/1},
  eprint = {2409.19750},
  file = {Full Text:/home/brian/papers/welman2024.pdf:application/pdf}
}

@inproceedings{kenyon2018cubical,
  title = {{CubiCal}: Fast Radio Interferometric Calibration},
  author = {Kenyon, Jonathan},
  year = {2018}
}
"""


def test_a_bib_file_parses_into_entries():
    entries = parse_bibtex(BIBTEX)

    assert [entry.citekey for entry in entries] == [
        "welman2024calibration",
        "kenyon2018cubical",
    ]


def test_an_entry_carries_the_fields_that_identify_its_paper():
    entry = parse_bibtex(BIBTEX)[0]

    assert entry.title == "A Paper About Calibration"
    assert entry.authors == "Welman, Brian and Smirnov, Oleg"
    assert entry.year == "2024"
    assert entry.doi == "10.1088/0004-637X/1"
    assert entry.arxiv_id == "2409.19750"


def test_braces_protecting_capitalisation_are_removed():
    assert parse_bibtex(BIBTEX)[1].title == (
        "CubiCal: Fast Radio Interferometric Calibration"
    )


def test_a_file_field_points_at_a_local_document():
    """Zotero writes `file = {Title:/abs/path.pdf:application/pdf}`, so a
    `.bib` export doubles as a batch of documents to ingest."""
    assert parse_bibtex(BIBTEX)[0].file_path == "/home/brian/papers/welman2024.pdf"


def test_an_entry_with_no_file_field_has_no_path():
    assert parse_bibtex(BIBTEX)[1].file_path is None


def test_an_entry_with_no_title_is_skipped():
    """Malformed entries are skipped rather than raising, so one bad record in
    a large export does not block the rest."""
    text = "@article{broken,\n  year = {2024}\n}\n" + BIBTEX

    assert len(parse_bibtex(text)) == 2


def test_an_empty_bib_file_yields_no_entries():
    assert parse_bibtex("") == []


def test_a_bib_file_is_read_from_disk(tmp_path: Path):
    path = tmp_path / "library.bib"
    path.write_text(BIBTEX, encoding="utf-8")

    assert len(parse_bibtex_file(path)) == 2


def test_a_bib_file_is_recognised_by_its_suffix():
    assert looks_like_bibtex("library.bib") is True
    assert looks_like_bibtex("library.BIB") is True
    assert looks_like_bibtex("paper.pdf") is False
