"""The frontmatter every corpus document carries.

`extra="forbid"` and the `owner` guard are the two rules with teeth here: the
first turns a key kennis does not understand into an error rather than a
silent drop, and the second decides who may overwrite a document.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kennis.engine.corpus.schema import (
    Bibliography,
    DocsFrontmatter,
    DocsPage,
    DocumentFrontmatter,
    LiteratureFrontmatter,
    NoteFrontmatter,
    Source,
    frontmatter_model_for,
    parse_frontmatter,
    unparse_frontmatter,
)


def a_source(**overrides: object) -> Source:
    fields: dict[str, object] = {
        "from": "arxiv:1101.1764",
        "via": "arxiv-html",
        "format": "html",
    }
    fields.update(overrides)
    return Source.model_validate(fields)


def a_note(**overrides: object) -> NoteFrontmatter:
    fields: dict[str, object] = {
        "id": "abcdefghij",
        "title": "A note",
        "owner": "user",
        "source": {"from": "path:/tmp/a.md", "via": "verbatim", "format": "markdown"},
    }
    fields.update(overrides)
    return NoteFrontmatter.model_validate(fields)


# ---------------------------------------------------------------------------
# The source block
# ---------------------------------------------------------------------------


def test_the_origin_is_spelled_from_on_disk():
    """Design section 4 writes the key as `source.from`; `from` is a Python
    keyword, so the model field is `origin` and the alias is what makes the
    design's own spelling expressible."""
    source = a_source()

    assert source.origin == "arxiv:1101.1764"
    assert source.model_dump(by_alias=True)["from"] == "arxiv:1101.1764"


def test_an_unknown_conversion_route_is_refused():
    with pytest.raises(ValidationError):
        a_source(via="telepathy")


def test_a_source_records_when_it_was_ingested():
    assert a_source().at is not None


# ---------------------------------------------------------------------------
# owner
# ---------------------------------------------------------------------------


def test_a_user_owned_document_is_yours():
    assert a_note(owner="user").owner == "user"


def test_a_pack_owns_its_documents_by_name():
    assert a_note(owner="pack:boepie").owner == "pack:boepie"


@pytest.mark.parametrize(
    "value",
    [
        # The old managed_by vocabulary. Refused rather than migrated: the
        # corpora are rebuildable and there is no compatibility obligation.
        "boepie",
        "kennis",
        "pack:",
        "pack:Boepie",
        "PACK:boepie",
        "",
        "user ",
    ],
)
def test_an_unrecognised_owner_is_refused(value: str):
    """kennis does not guess, does not silently treat it as `user`, and ships
    no migration."""
    with pytest.raises(ValidationError):
        a_note(owner=value)


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------


def test_a_key_kennis_does_not_understand_is_an_error():
    """With pydantic's default it would be silently dropped, so a document
    written by a newer kennis would read cleanly and be quietly missing
    content."""
    with pytest.raises(ValidationError):
        a_note(tags=["unexpected"])


def test_the_rule_holds_inside_a_nested_block_too():
    with pytest.raises(ValidationError):
        LiteratureFrontmatter.model_validate(
            {
                "id": "abcdefghij",
                "title": "A paper",
                "owner": "user",
                "source": {"from": "arxiv:1", "via": "arxiv-html", "format": "html"},
                "bib": {"citekey": "welman2024", "impact_factor": 3},
            }
        )


# ---------------------------------------------------------------------------
# The collections
# ---------------------------------------------------------------------------


def test_a_note_adds_nothing_to_the_base():
    """Notes have no natural key by design, so the base is the whole of it."""
    assert set(NoteFrontmatter.model_fields) == set(DocumentFrontmatter.model_fields)


def test_literature_requires_a_bibliography():
    with pytest.raises(ValidationError):
        LiteratureFrontmatter.model_validate(
            {
                "id": "abcdefghij",
                "title": "A paper",
                "owner": "user",
                "source": {"from": "arxiv:1", "via": "arxiv-html", "format": "html"},
            }
        )


def test_a_bibliography_needs_only_a_citekey():
    """The rest is enrichment, and a paper identified by citekey alone is a
    legitimate state."""
    assert Bibliography(citekey="welman2024").doi is None


def test_a_docs_page_names_its_project_and_page():
    page = DocsPage(project="numpy", page="quickstart")

    assert (page.project, page.page) == ("numpy", "quickstart")


@pytest.mark.parametrize(
    ("collection", "model"),
    [
        ("notes", NoteFrontmatter),
        ("literature", LiteratureFrontmatter),
        ("docs", DocsFrontmatter),
    ],
)
def test_each_collection_has_its_own_model(collection: str, model: type[object]):
    assert frontmatter_model_for(collection) is model


def test_an_unknown_collection_is_refused():
    from kennis.engine.errors import UnknownCollection

    with pytest.raises(UnknownCollection):
        frontmatter_model_for("papers")


# ---------------------------------------------------------------------------
# id_from
# ---------------------------------------------------------------------------


def test_a_derived_identifier_records_the_key_it_came_from():
    """Auditable rather than guessable: a checker can re-derive the identifier
    and compare."""
    note = a_note(id_from="arxiv:1101.1764")

    assert note.id_from == "arxiv:1101.1764"


def test_a_randomly_minted_identifier_records_nothing():
    """Absence is the note case, and the only case."""
    assert a_note().id_from is None


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_what_is_written_validates_again_unchanged():
    """`extra="forbid"` makes this worth asserting: a field that dumps under
    one spelling and validates under another would fail here rather than at
    the next milestone."""
    original = LiteratureFrontmatter.model_validate(
        {
            "id": "abcdefghij",
            "title": "A paper",
            "owner": "pack:boepie",
            "id_from": "arxiv:1101.1764",
            "source": {
                "from": "arxiv:1101.1764",
                "via": "arxiv-html",
                "format": "html",
                "sha256": "0" * 64,
            },
            "bib": {"citekey": "welman2024", "arxiv_id": "1101.1764"},
        }
    )

    written = unparse_frontmatter(original)
    read_back = parse_frontmatter("literature", written)

    assert read_back == original


def test_an_absent_optional_field_is_left_out_of_the_file_entirely():
    """Saying so by omission is smaller than a file full of nulls, and
    honest."""
    written = unparse_frontmatter(a_note())

    assert "id_from" not in written
    assert "sha256" not in written["source"]


def test_the_written_mapping_is_plain_data():
    """`yaml.safe_dump` refuses a datetime object, so the timestamp has to
    leave the model as a string."""
    written = unparse_frontmatter(a_note())

    assert isinstance(written["source"]["at"], str)
