"""Surrogate identifiers: derived from identity, never from content.

The two properties these tests defend are the ones that make a surrogate
worth having. It is stable, so a handle survives a retitle or a move; and it
is reproducible from the natural key, so two machines that fetch the same
paper write byte-identical files and git has nothing to resolve.
"""

from __future__ import annotations

import string
import subprocess
import sys

import pytest

from kennis.engine.corpus.ids import (
    ID_ALPHABET,
    ID_LENGTH,
    derive_id,
    mint_id,
    natural_key_for_docs,
    natural_key_for_literature,
)


def test_a_derived_identifier_has_the_shape_of_a_minted_one():
    """Nothing downstream may be able to tell the two apart by looking."""
    derived = derive_id("arxiv:1101.1764")

    assert len(derived) == ID_LENGTH
    assert set(derived) <= set(ID_ALPHABET)
    assert set(ID_ALPHABET) == set(string.ascii_lowercase + string.digits)


def test_the_same_natural_key_derives_the_same_identifier():
    """Machine A and machine B fetch the same paper and must write the same
    bytes, or git reports an add/add conflict on every paper both hold."""
    assert derive_id("arxiv:1101.1764") == derive_id("arxiv:1101.1764")


def test_different_natural_keys_derive_different_identifiers():
    assert derive_id("arxiv:1101.1764") != derive_id("arxiv:1101.1765")


def test_the_kind_of_key_is_part_of_what_is_hashed():
    """A DOI that happens to spell an arXiv identifier must not collide with
    it, which is what the namespace prefix is for."""
    assert derive_id("arxiv:1101.1764") != derive_id("doi:1101.1764")


def test_a_minted_identifier_avoids_the_ones_already_taken():
    taken = {mint_id(set()) for _ in range(50)}

    fresh = mint_id(taken)

    assert fresh not in taken
    assert len(fresh) == ID_LENGTH


def test_minting_is_not_derivation():
    """Two notes created from nothing must not share an identifier."""
    assert mint_id(set()) != mint_id(set())


class TestLiteraturePrecedence:
    """A paper may carry an arXiv identifier, a DOI and a bibcode. Exactly one
    decides the surrogate identifier, and which one is fixed rather than
    whichever happened to be discovered first."""

    def test_the_arxiv_identifier_wins(self):
        key = natural_key_for_literature(
            arxiv_id="1101.1764", doi="10.1088/0004-637X/1", bibcode="2011ApJ...1B"
        )

        assert key == "arxiv:1101.1764"

    def test_the_doi_comes_next(self):
        key = natural_key_for_literature(
            arxiv_id=None, doi="10.1088/0004-637X/1", bibcode="2011ApJ...1B"
        )

        assert key == "doi:10.1088/0004-637X/1"

    def test_the_bibcode_is_the_last_resort(self):
        key = natural_key_for_literature(
            arxiv_id=None, doi=None, bibcode="2011ApJ...1B"
        )

        assert key == "bibcode:2011ApJ...1B"

    def test_a_paper_with_no_identifier_at_all_has_no_natural_key(self):
        """Literature refuses such a document elsewhere; here the answer is
        simply that there is nothing to derive from."""
        assert natural_key_for_literature(arxiv_id=None, doi=None, bibcode=None) is None

    def test_an_empty_identifier_does_not_count_as_one(self):
        key = natural_key_for_literature(arxiv_id="", doi="10.1088/x", bibcode=None)

        assert key == "doi:10.1088/x"


def test_a_docs_page_is_keyed_by_project_and_page():
    assert natural_key_for_docs(project="numpy", page="quickstart") == (
        "docs:numpy/quickstart"
    )


def test_two_pages_of_one_project_are_different_documents():
    first = derive_id(natural_key_for_docs(project="numpy", page="quickstart"))
    second = derive_id(natural_key_for_docs(project="numpy", page="install"))

    assert first != second


@pytest.mark.parametrize(
    "key",
    [
        "arxiv:1101.1764",
        "doi:10.1088/0004-637X/1",
        "bibcode:2011ApJ...727...39B",
        "docs:numpy/reference/generated/numpy.zeros",
    ],
)
def test_every_kind_of_key_derives_a_well_formed_identifier(key: str):
    identifier = derive_id(key)

    assert len(identifier) == ID_LENGTH
    assert set(identifier) <= set(ID_ALPHABET)


def test_an_empty_key_is_refused_rather_than_hashed():
    """Hashing "" would give every keyless document the same identifier, which
    is worse than failing."""
    with pytest.raises(ValueError):
        derive_id("")


def test_the_derivation_is_stable_across_independent_runs():
    """The plan asks for two *runs*, not two calls, and it is right to: a
    derivation that depended on anything per-process - a randomised hash seed,
    an interpreter detail - would pass inside one process and still give two
    machines different bytes for the same paper.
    """
    program = (
        "from kennis.engine.corpus.ids import derive_id; "
        "print(derive_id('arxiv:1101.1764'))"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=True,
        ).stdout.strip()
        for _ in range(2)
    ]

    assert runs[0] == runs[1] == derive_id("arxiv:1101.1764")
