"""Reading a collection that holds a document kennis cannot validate.

Two properties in tension, and both have to hold. A broken document must be
*reported* rather than silently skipped - a corpus served nine tenths of is
worse than one that says what is wrong. And it must not cost every other
operation, which is what happens when the only way to learn a collection's
contents is to validate all of it.

The resolution is that the facts a batch needs about a document - its
identifier and its checksum - are plain YAML keys and do not require the
document to be valid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import inspect_document, read_document
from kennis.engine.corpus.layout import WRAPPED_DOCUMENT_FILENAME
from kennis.engine.errors import DocumentInvalid

VALID = """---
id: abcdefghij
title: A note
owner: user
source:
  from: 'path:/tmp/a.md'
  via: verbatim
  format: markdown
  sha256: deadbeef
---

Body.
"""

# An unknown key. The document is otherwise perfectly formed, which is what
# makes this the likely case: frontmatter is YAML, and adding a key to YAML is
# what anybody would try.
UNKNOWN_KEY = VALID.replace("title:", "tags: [physics]\ntitle:")

# Not parseable as YAML at all - a truncated write, a crashed editor.
BROKEN_YAML = "---\nid: [unclosed\ntitle: A note\n---\n\nBody.\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Every failure is a domain exception
# ---------------------------------------------------------------------------


def test_unparseable_yaml_is_a_domain_error_not_the_parsers(tmp_path: Path):
    """A front end renders a `DocumentInvalid` as `error: ...`; a
    `yaml.parser.ParserError` reaches it as an unhandled traceback."""
    path = write(tmp_path / "broken.md", BROKEN_YAML)

    with pytest.raises(DocumentInvalid) as raised:
        read_document(path, collection="notes")

    assert str(path) in str(raised.value)
    assert "YAML" in str(raised.value)


def test_a_file_that_cannot_be_decoded_is_a_domain_error(tmp_path: Path):
    path = tmp_path / "binary.md"
    path.write_bytes(b"\xff\xfe\x00\x01not text at all")

    with pytest.raises(DocumentInvalid):
        read_document(path, collection="notes")


def test_a_file_that_is_not_there_is_a_domain_error(tmp_path: Path):
    with pytest.raises(DocumentInvalid):
        read_document(tmp_path / "absent.md", collection="notes")


# ---------------------------------------------------------------------------
# Inspecting without validating
# ---------------------------------------------------------------------------


def test_inspecting_a_valid_document_finds_no_problem(tmp_path: Path):
    path = write(tmp_path / "a.md", VALID)

    facts = inspect_document(path, collection="notes")

    assert facts.problem is None
    assert facts.identifier == "abcdefghij"
    assert facts.checksum == "deadbeef"


def test_the_uniqueness_facts_survive_a_validation_failure(tmp_path: Path):
    """This is what makes the whole approach possible: `id` and
    `source.sha256` are plain YAML keys, so a document that fails validation
    still reserves its identifier and still answers for its content."""
    path = write(tmp_path / "a.md", UNKNOWN_KEY)

    facts = inspect_document(path, collection="notes")

    assert facts.identifier == "abcdefghij"
    assert facts.checksum == "deadbeef"
    assert facts.problem is not None
    assert "tags" in facts.problem


def test_a_document_whose_yaml_will_not_parse_still_reserves_its_filename(
    tmp_path: Path,
):
    """Its identifier cannot be known, but its name on disk is taken, and a
    new document must not be written over it."""
    path = write(tmp_path / "broken.md", BROKEN_YAML)

    facts = inspect_document(path, collection="notes")

    assert facts.identifier is None
    assert facts.reserved_filename == "broken.md"
    assert facts.problem is not None


def test_a_wrapped_document_reserves_its_wrapper_name(tmp_path: Path):
    """Its own file is always `content.md`, so what a new document's candidate
    filename would collide with is the wrapper directory."""
    path = write(tmp_path / "A paper" / WRAPPED_DOCUMENT_FILENAME, VALID)

    facts = inspect_document(path, collection="notes")

    assert facts.reserved_filename == "A paper.md"


def test_inspecting_never_raises(tmp_path: Path):
    """It is the lenient reader, and a caller uses it precisely because it
    cannot afford to fail."""
    for name, text in (
        ("a.md", VALID),
        ("b.md", UNKNOWN_KEY),
        ("c.md", BROKEN_YAML),
        ("d.md", "no frontmatter at all\n"),
    ):
        assert inspect_document(write(tmp_path / name, text), collection="notes")


# ---------------------------------------------------------------------------
# The collection survey
# ---------------------------------------------------------------------------


def test_a_survey_sees_every_document_valid_or_not(tmp_path: Path):
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "unknown-key.md", UNKNOWN_KEY)
    write(collection.path / "broken.md", BROKEN_YAML)

    survey = collection.survey()

    assert len(survey) == 3
    assert sum(1 for facts in survey if facts.problem is not None) == 2


def test_reading_a_collection_never_raises_over_one_document(tmp_path: Path):
    """The failure is in the return value rather than in an exception: these
    documents are there, kennis cannot read them, and every caller has to
    decide what that means for it."""
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "unknown-key.md", UNKNOWN_KEY)

    contents = collection.contents()

    assert len(contents.documents) == 1
    assert len(contents.unreadable) == 1
    assert contents.unreadable[0].problem is not None


def test_a_survey_of_an_absent_collection_is_empty(tmp_path: Path):
    assert Collection(root=tmp_path, name="notes").survey() == []


def test_a_problem_names_the_document_it_is_about(tmp_path: Path):
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "unknown-key.md", UNKNOWN_KEY)

    problems = [facts.problem for facts in collection.survey() if facts.problem]

    assert "unknown-key.md" in problems[0]


# ---------------------------------------------------------------------------
# Overwriting
# ---------------------------------------------------------------------------


def test_a_document_that_cannot_be_read_is_not_overwritten(tmp_path: Path):
    """If kennis cannot tell whether the file in the way is the same document,
    clobbering it is precisely the data loss the guard exists to prevent."""
    from kennis.engine.corpus.document import write_document
    from kennis.engine.corpus.schema import NoteFrontmatter

    path = write(tmp_path / "a.md", BROKEN_YAML)
    frontmatter = NoteFrontmatter.model_validate(
        {
            "id": "zyxwvutsrq",
            "title": "A note",
            "owner": "user",
            "source": {
                "from": "path:/tmp/a.md",
                "via": "verbatim",
                "format": "markdown",
            },
        }
    )

    with pytest.raises(ValueError):
        write_document(path, frontmatter=frontmatter, body="new")

    assert path.read_text(encoding="utf-8") == BROKEN_YAML


# ---------------------------------------------------------------------------
# Reading past a document that cannot be read
# ---------------------------------------------------------------------------


def test_contents_separates_what_could_be_read_from_what_could_not(tmp_path: Path):
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "unknown-key.md", UNKNOWN_KEY)
    write(collection.path / "broken.md", BROKEN_YAML)

    contents = collection.contents()

    assert [document.md_path.name for document in contents.documents] == ["good.md"]
    assert {facts.md_path.name for facts in contents.unreadable} == {
        "unknown-key.md",
        "broken.md",
    }


def test_resolving_works_past_an_unrelated_broken_document(tmp_path: Path):
    """A document kennis cannot validate cannot be returned by `resolve`
    anyway, so it contributes nothing to the answer - and must not cost it."""
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "broken.md", BROKEN_YAML)

    assert collection.resolve("abcdefghij").md_path.name == "good.md"


def test_an_alias_resolves_past_a_broken_document(tmp_path: Path):
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "broken.md", BROKEN_YAML)

    assert collection.resolve("A note").md_path.name == "good.md"


def test_asking_for_the_broken_document_itself_says_why(tmp_path: Path):
    """Its identifier is a plain YAML key, so it is still known. Answering
    `DocumentNotFound` would send the reader looking for a document that is
    there."""
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "broken-but-identified.md", UNKNOWN_KEY)

    with pytest.raises(DocumentInvalid) as raised:
        collection.resolve("abcdefghij")

    assert "broken-but-identified.md" in str(raised.value)
    assert "tags" in str(raised.value)


def test_a_broken_document_contributes_no_aliases(tmp_path: Path):
    """Nothing can be addressed by a key kennis could not read."""
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "broken.md", BROKEN_YAML)

    assert collection.aliases() == {}


def test_a_broken_document_does_not_make_a_good_ones_alias_ambiguous(
    tmp_path: Path,
):
    collection = Collection(root=tmp_path, name="notes")
    write(collection.path / "good.md", VALID)
    write(collection.path / "also-titled-a-note.md", UNKNOWN_KEY)

    assert collection.aliases()["a note"] == "abcdefghij"
