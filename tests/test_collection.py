"""Walking a collection, and resolving a handle to a document.

A document is addressed by an opaque identifier, but what people and curated
notes actually write down is a citekey, an arXiv identifier, a DOI, a
`project/page` pair or a title. Resolving those keeps such references working
without giving up the identifier's stability across renames.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import write_document
from kennis.engine.corpus.layout import (
    WRAPPED_DOCUMENT_FILENAME,
    collection_root,
    title_filename,
    unique_filename,
)
from kennis.engine.corpus.schema import (
    DocsFrontmatter,
    LiteratureFrontmatter,
    NoteFrontmatter,
)
from kennis.engine.errors import DocumentNotFound, UnknownCollection

BODY = "Some text.\n"


def _free_name(root: Path, title: str) -> str:
    """What the add path will do: two documents may share a title, and the
    second one is suffixed rather than overwriting the first."""
    taken = {entry.name for entry in root.iterdir()} if root.is_dir() else set()
    return unique_filename(title_filename(title), taken)


def a_paper(
    root: Path, *, identifier: str, title: str, **bib: Any
) -> LiteratureFrontmatter:
    frontmatter = LiteratureFrontmatter.model_validate(
        {
            "id": identifier,
            "title": title,
            "owner": "user",
            "source": {"from": "arxiv:x", "via": "arxiv-html", "format": "html"},
            "bib": {"citekey": bib.pop("citekey", identifier), **bib},
        }
    )
    write_document(root / _free_name(root, title), frontmatter=frontmatter, body=BODY)
    return frontmatter


def a_page(root: Path, *, identifier: str, project: str, page: str) -> DocsFrontmatter:
    frontmatter = DocsFrontmatter.model_validate(
        {
            "id": identifier,
            "title": f"{project} {page}",
            "owner": "user",
            "source": {"from": "url:https://x/y", "via": "html", "format": "html"},
            "docs": {"project": project, "page": page},
        }
    )
    write_document(root / project / f"{page}.md", frontmatter=frontmatter, body=BODY)
    return frontmatter


def a_note(root: Path, *, identifier: str, title: str) -> NoteFrontmatter:
    frontmatter = NoteFrontmatter.model_validate(
        {
            "id": identifier,
            "title": title,
            "owner": "user",
            "source": {"from": "path:/tmp/x", "via": "verbatim", "format": "markdown"},
        }
    )
    write_document(root / _free_name(root, title), frontmatter=frontmatter, body=BODY)
    return frontmatter


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def test_an_absent_collection_holds_no_documents(tmp_path: Path):
    """A fresh machine with nothing fetched is a normal state, not an error."""
    collection = Collection(root=tmp_path, name="notes")

    assert collection.contents().documents == []


def test_every_document_in_the_collection_is_found(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First")
    a_paper(root, identifier="bbbbbbbbbb", title="Second")

    collection = Collection(root=tmp_path, name="literature")

    assert {document.id for document in collection.contents().documents} == {
        "aaaaaaaaaa",
        "bbbbbbbbbb",
    }


def test_a_directory_is_a_group_and_the_walk_descends_into_it(tmp_path: Path):
    """No metadata field and no reserved bucket name: a document is told from
    a group by filesystem shape alone."""
    root = collection_root(tmp_path, "docs")
    a_page(root, identifier="aaaaaaaaaa", project="numpy", page="quickstart")

    collection = Collection(root=tmp_path, name="docs")

    assert [document.id for document in collection.contents().documents] == [
        "aaaaaaaaaa"
    ]


def test_a_directory_holding_content_md_is_one_document_not_a_group(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    frontmatter = LiteratureFrontmatter.model_validate(
        {
            "id": "aaaaaaaaaa",
            "title": "Wrapped",
            "owner": "user",
            "source": {"from": "arxiv:x", "via": "arxiv-html", "format": "html"},
            "bib": {"citekey": "wrapped"},
        }
    )
    write_document(
        root / "Wrapped.md",
        frontmatter=frontmatter,
        body=BODY,
        assets={"figure.png": b"x"},
    )

    documents = Collection(root=tmp_path, name="literature").contents().documents

    assert len(documents) == 1
    assert documents[0].md_path.name == WRAPPED_DOCUMENT_FILENAME


def test_bookkeeping_files_are_not_documents(tmp_path: Path):
    root = collection_root(tmp_path, "notes")
    a_note(root, identifier="aaaaaaaaaa", title="Real")
    (root / "user-papers.json").write_text("{}", encoding="utf-8")
    (root / ".hidden").mkdir()

    assert len(Collection(root=tmp_path, name="notes").contents().documents) == 1


def test_an_unknown_collection_is_refused(tmp_path: Path):
    with pytest.raises(UnknownCollection):
        Collection(root=tmp_path, name="papers")


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_a_document_is_reachable_by_its_identifier(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First")

    collection = Collection(root=tmp_path, name="literature")

    assert collection.resolve("aaaaaaaaaa").id == "aaaaaaaaaa"


def test_a_document_is_reachable_by_citekey_arxiv_identifier_and_doi(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(
        root,
        identifier="aaaaaaaaaa",
        title="First",
        citekey="welman2024",
        arxiv_id="1101.1764",
        doi="10.1088/0004-637X/1",
    )

    collection = Collection(root=tmp_path, name="literature")

    for handle in ("welman2024", "1101.1764", "10.1088/0004-637X/1", "First"):
        assert collection.resolve(handle).id == "aaaaaaaaaa", handle


def test_a_document_is_reachable_by_the_filename_it_has_on_disk(tmp_path: Path):
    """The name `corpus tree` shows and the name a shell completes, with or
    without the extension. A person looking at the directory has the filename
    in front of them and nothing else."""
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First light")
    filename = next(root.iterdir()).name

    collection = Collection(root=tmp_path, name="literature")

    assert filename.endswith(".md")
    assert collection.resolve(filename).id == "aaaaaaaaaa"
    assert collection.resolve(filename.removesuffix(".md")).id == "aaaaaaaaaa"


def test_a_filename_that_two_documents_would_share_resolves_to_nothing(tmp_path: Path):
    """The same rule every other alias follows: a key two documents answer to
    addresses neither. A filename cannot collide on disk, but its stem can
    collide with another document's title."""
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="Shared name")
    a_paper(root, identifier="bbbbbbbbbb", title="Shared name.md")

    collection = Collection(root=tmp_path, name="literature")

    with pytest.raises(DocumentNotFound):
        collection.resolve("Shared name.md")


def test_a_docs_page_is_reachable_by_project_and_page(tmp_path: Path):
    root = collection_root(tmp_path, "docs")
    a_page(root, identifier="aaaaaaaaaa", project="numpy", page="quickstart")

    collection = Collection(root=tmp_path, name="docs")

    assert collection.resolve("numpy/quickstart").id == "aaaaaaaaaa"


def test_casing_need_not_be_remembered_exactly(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First", citekey="Welman2024")

    collection = Collection(root=tmp_path, name="literature")

    assert collection.resolve("welman2024").id == "aaaaaaaaaa"


def test_a_real_identifier_is_never_shadowed_by_an_alias(tmp_path: Path):
    """Resolution consults the alias map only after the literal lookup has
    missed, so a document whose citekey happens to be another document's
    identifier cannot hijack it."""
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First", citekey="first")
    a_paper(root, identifier="bbbbbbbbbb", title="Second", citekey="aaaaaaaaaa")

    collection = Collection(root=tmp_path, name="literature")

    assert collection.resolve("aaaaaaaaaa").id == "aaaaaaaaaa"


def test_an_ambiguous_alias_resolves_to_nothing_rather_than_to_a_guess(tmp_path: Path):
    """Two documents sharing a key make that key useless, and the honest
    answer is that it addresses nothing."""
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First", citekey="shared")
    a_paper(root, identifier="bbbbbbbbbb", title="Second", citekey="shared")

    collection = Collection(root=tmp_path, name="literature")

    with pytest.raises(DocumentNotFound):
        collection.resolve("shared")


def test_an_unambiguous_alias_survives_its_neighbour_being_ambiguous(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="Same", citekey="first")
    a_paper(root, identifier="bbbbbbbbbb", title="Same", citekey="second")

    collection = Collection(root=tmp_path, name="literature")

    assert collection.resolve("first").id == "aaaaaaaaaa"
    with pytest.raises(DocumentNotFound):
        collection.resolve("Same")


def test_a_handle_nobody_ever_used_is_not_found(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First")

    collection = Collection(root=tmp_path, name="literature")

    with pytest.raises(DocumentNotFound) as raised:
        collection.resolve("nothing-like-this")

    assert "nothing-like-this" in str(raised.value)
    assert raised.value.resolution


def test_the_alias_map_drops_the_ambiguous_key_and_keeps_the_rest(tmp_path: Path):
    root = collection_root(tmp_path, "literature")
    a_paper(root, identifier="aaaaaaaaaa", title="First", citekey="shared")
    a_paper(root, identifier="bbbbbbbbbb", title="Second", citekey="shared")

    aliases = Collection(root=tmp_path, name="literature").aliases()

    assert "shared" not in aliases
    assert aliases["first"] == "aaaaaaaaaa"


# ---------------------------------------------------------------------------
# Removal through the collection
# ---------------------------------------------------------------------------


def test_a_removed_document_stops_being_found(tmp_path: Path):
    root = collection_root(tmp_path, "notes")
    a_note(root, identifier="aaaaaaaaaa", title="Doomed")
    collection = Collection(root=tmp_path, name="notes")

    collection.remove(collection.resolve("aaaaaaaaaa"))

    assert collection.contents().documents == []
    with pytest.raises(DocumentNotFound):
        collection.resolve("aaaaaaaaaa")
