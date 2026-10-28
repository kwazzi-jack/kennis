"""An author list follows BibLaTeX's name-list rule (Brian, 2026-10-28).

Names are separated by ` and `, and a name holding that word is protected
by braces, `{Barnes and Noble}`; `and others` ends a list cut short. Every
place kennis splits a list or makes one goes through `names.py`.
"""

from __future__ import annotations

import httpx
import pytest

from kennis.engine.literature.citekeys import derive_citekey, literature_stem
from kennis.engine.literature.metadata import lookup_doi_metadata
from kennis.engine.literature.names import (
    joined_names,
    protected,
    split_names,
    unbraced,
)
from kennis.engine.pack.schema import LiteratureEntry, authors_from_line


@pytest.mark.parametrize(
    ("line", "names"),
    [
        ("Smirnov, O and Heywood, I", ["Smirnov, O", "Heywood, I"]),
        ("{Barnes and Noble} and Smith, J", ["{Barnes and Noble}", "Smith, J"]),
        ("Smirnov, O and others", ["Smirnov, O", "others"]),
        ("{van der Horst}, A and Fender, R", ["{van der Horst}, A", "Fender, R"]),
        ("Smirnov, O  and\tHeywood, I", ["Smirnov, O", "Heywood, I"]),
        ("Sandoval, A", ["Sandoval, A"]),
        ("Anderson, B", ["Anderson, B"]),
        ("", []),
    ],
)
def test_a_list_is_split_only_outside_braces(line: str, names: list[str]):
    assert split_names(line) == names


def test_a_name_holding_and_is_braced_and_survives_the_round_trip():
    names = [protected(name) for name in ["Barnes and Noble", "Smith, J"]]

    assert names == ["{Barnes and Noble}", "Smith, J"]
    assert split_names(joined_names(names)) == names


def test_a_name_already_braced_is_not_braced_again():
    assert protected("{Barnes and Noble}") == "{Barnes and Noble}"


def test_braces_are_taken_off_for_a_reader():
    assert unbraced("{van der Horst}, A") == "van der Horst, A"


def test_a_pack_entry_keeps_a_braced_name_as_one():
    assert authors_from_line("{EHT Collaboration and others} and Akiyama, K") == [
        "{EHT Collaboration and others}",
        "Akiyama, K",
    ]
    entry = LiteratureEntry.model_validate(
        {"identifier": "1101.1764", "authors": ["{Barnes and Noble}", "Smith, J"]}
    )
    assert entry.author_line == "{Barnes and Noble} and Smith, J"


def test_a_braced_name_is_its_own_surname():
    """BibLaTeX reads a name wholly in braces as one last name."""
    assert derive_citekey(
        authors="{Barnes and Noble} and Smith, J", year="2019", title="Books"
    ).startswith("barnesAndNoble")
    assert (
        literature_stem(
            title="Books", authors="{Barnes and Noble} and Smith, J", year="2019"
        )
        == "Books - Barnes and Noble et al - 2019"
    )


def test_one_braced_author_has_no_et_al():
    assert (
        literature_stem(title="Books", authors="{Barnes and Noble}", year="2019")
        == "Books - Barnes and Noble - 2019"
    )


def test_a_registry_s_corporate_name_is_protected():
    answer = {
        "DOI": "10.3847/2041-8213/ab0ec7",
        "title": "First M87 results",
        "author": [
            {"literal": "Event Horizon Telescope and Friends"},
            {"family": "Akiyama", "given": "Kazunori"},
        ],
        "issued": {"date-parts": [[2019]]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=answer, headers={"content-type": "application/json"}
        )

    found = lookup_doi_metadata(
        "10.3847/2041-8213/ab0ec7",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert found is not None
    assert split_names(found.authors) == [
        "{Event Horizon Telescope and Friends}",
        "Akiyama, Kazunori",
    ]
