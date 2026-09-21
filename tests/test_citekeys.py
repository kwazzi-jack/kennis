"""Minting a name for a paper that arrived without one.

Derivation is the fallback, not the rule: a paper that came with a citekey
keeps it, because that key is what the user's own bibliography already cites.
"""

from __future__ import annotations

import pytest

from kennis.engine.literature.citekeys import derive_citekey, unique_citekey


def test_a_citekey_is_surname_then_title_words_then_year():
    """The style a Zotero export already uses, so a derived key sits beside
    an exported one without looking out of place."""
    assert (
        derive_citekey(
            authors="Smirnov, Oleg",
            year="2011",
            title="Revisiting the radio interferometer measurement equation",
        )
        == "smirnovRevisitingRadioInterferometer2011"
    )


def test_the_bibliography_convention_for_names_is_understood():
    """`Last, First` is what a Zotero export writes."""
    assert (
        derive_citekey(authors="Kenyon, Jonathan S.", year="2018", title="CubiCal")
        == "kenyonCubical2018"
    )


def test_the_api_convention_for_names_is_understood():
    """`First M. Last` is what arXiv's Atom API returns, and that is the real
    caller when a bare arXiv identifier is all there was."""
    assert (
        derive_citekey(authors="Jonathan S. Kenyon", year="2018", title="CubiCal")
        == "kenyonCubical2018"
    )


def test_only_the_first_author_is_used():
    assert derive_citekey(
        authors="Welman, Brian and Smirnov, Oleg", year="2024", title="Calibration"
    ).startswith("welman")


def test_stopwords_are_skipped_in_the_title():
    """Two *meaningful* words, so `The Effect of Noise` reads
    `effectNoise` rather than `theEffect`."""
    assert (
        derive_citekey(
            authors="Welman, Brian", year="2024", title="The Effect of Noise on Gains"
        )
        == "welmanEffectNoiseGains2024"
    )


def test_a_paper_with_no_author_falls_back_to_a_real_word():
    """A local PDF carries no bibliography, so there is no surname to take.
    `paper` is deliberately a word rather than a marker, because the key is
    something a person will read and type."""
    assert derive_citekey(authors="", year="2018", title="Radio Interferometry") == (
        "paperRadioInterferometry2018"
    )


def test_punctuation_in_a_surname_is_dropped():
    assert derive_citekey(
        authors="O'Brien, Sean", year="2020", title="Gains"
    ).startswith("oBrien")


def test_a_title_of_nothing_but_stopwords_still_yields_a_key():
    assert derive_citekey(authors="Welman, Brian", year="2024", title="On the") == (
        "welman2024"
    )


# ---------------------------------------------------------------------------
# Disambiguation
# ---------------------------------------------------------------------------


def test_an_unused_citekey_is_taken_as_it_is():
    assert unique_citekey("welmanCalibration2024", set()) == "welmanCalibration2024"


def test_a_taken_citekey_is_lettered_as_zotero_letters_them():
    taken = {"welmanCalibration2024", "welmanCalibration2024a"}

    assert unique_citekey("welmanCalibration2024", taken) == "welmanCalibration2024b"


def test_past_z_the_suffix_is_numbered_rather_than_fatal():
    """Title-derived keys - what a folder of PDFs with no bibliography
    produces - collide far more readily than the author-and-year keys the
    lettering convention was written for, and raising would abort a whole
    batch over one document."""
    base = "paperRadioInterferometry2018"
    taken = {base} | {f"{base}{letter}" for letter in "abcdefghijklmnopqrstuvwxyz"}

    assert unique_citekey(base, taken) == f"{base}27"


def test_numbering_continues_past_the_first_number():
    base = "paperRadioInterferometry2018"
    taken = (
        {base}
        | {f"{base}{letter}" for letter in "abcdefghijklmnopqrstuvwxyz"}
        | {f"{base}27", f"{base}28"}
    )

    assert unique_citekey(base, taken) == f"{base}29"


@pytest.mark.parametrize("year", ["", "2024"])
def test_a_key_is_produced_whether_or_not_the_year_is_known(year: str):
    assert derive_citekey(authors="Welman, Brian", year=year, title="Gains")
