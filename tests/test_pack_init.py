"""`pack init`: the scaffold. Milestone 7 unit 3.

A pack file is edited by hand for the rest of its life, so what matters
here is not only that the result parses but that it is a file a person can
work in: the editor header, the section headings, the comments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.scaffold import SCHEMA_URL, scaffold_pack
from kennis.engine.pack.schema import load_pack
from kennis.engine.pack.validate import validate_pack


def test_the_scaffold_is_a_file_kennis_would_accept(tmp_path: Path):
    """Run through the same parser every other pack goes through, so a
    scaffold cannot be a file kennis itself refuses."""
    path = scaffold_pack(tmp_path / "stimela.ken.yml", identifier="boepie", name="n")

    pack = load_pack(path.read_text(encoding="utf-8"))

    assert pack.pack.id == "boepie"
    assert pack.pack.name == "n"


def test_the_scaffold_validates_with_no_problems(tmp_path: Path):
    """Stronger than parsing: a scaffold that declared a `source:` would
    report `source-missing` the moment it was written."""
    path = scaffold_pack(tmp_path / "stimela.ken.yml", identifier="boepie", name="n")

    report = validate_pack(path)

    assert report.ok, report.problems


def test_the_editor_header_is_the_first_line(tmp_path: Path):
    """Section 18: one comment gives an author with no kennis installed
    completion and inline errors. It is worth nothing on line 40."""
    path = scaffold_pack(tmp_path / "p.ken.yml", identifier="boepie", name="n")

    first = path.read_text(encoding="utf-8").splitlines()[0]

    assert first.startswith("# yaml-language-server: $schema=")
    assert SCHEMA_URL in first


def test_the_header_names_the_versioned_schema_file(tmp_path: Path):
    """The path is versioned so schema 1 never changes meaning; a header
    pointing at an unversioned name would start meaning something else the
    day schema 2 shipped."""
    del tmp_path
    assert SCHEMA_URL.endswith("/ken-1.json")


def test_the_version_defaults_and_can_be_given(tmp_path: Path):
    default = scaffold_pack(tmp_path / "a.ken.yml", identifier="a", name="n")
    given = scaffold_pack(
        tmp_path / "b.ken.yml", identifier="b", name="n", version="2.4.0"
    )

    assert load_pack(default.read_text(encoding="utf-8")).pack.version == "0.1.0"
    assert load_pack(given.read_text(encoding="utf-8")).pack.version == "2.4.0"


def test_a_description_is_written_when_given_and_absent_when_not(tmp_path: Path):
    with_one = scaffold_pack(
        tmp_path / "a.ken.yml", identifier="a", name="n", description="Radio stuff."
    )
    without = scaffold_pack(tmp_path / "b.ken.yml", identifier="b", name="n")

    assert load_pack(with_one.read_text(encoding="utf-8")).pack.description == (
        "Radio stuff."
    )
    assert load_pack(without.read_text(encoding="utf-8")).pack.description is None


def test_an_existing_file_is_refused_and_not_overwritten(tmp_path: Path):
    """A pack file holds hand-written declarations. Rewriting it would
    delete them, and there is no history to get them back from - a pack
    lives in the provider's repository, not in kennis."""
    path = tmp_path / "stimela.ken.yml"
    path.write_text("corpus:\n  notes:\n    - source: notes/\n", encoding="utf-8")

    with pytest.raises(PackInvalid):
        scaffold_pack(path, identifier="boepie", name="n")

    assert "source: notes/" in path.read_text(encoding="utf-8")


def test_an_id_that_is_not_a_slug_is_refused_before_anything_is_written(
    tmp_path: Path,
):
    path = tmp_path / "stimela.ken.yml"

    with pytest.raises(PackInvalid):
        scaffold_pack(path, identifier="Not A Slug", name="n")

    assert not path.exists()


def test_the_scaffold_declares_no_content(tmp_path: Path):
    """Which is why `validate` may refuse a `source:` naming a directory
    that is not there: the state it would break - a declaration written
    before its content - is one an author creates deliberately."""
    path = scaffold_pack(tmp_path / "p.ken.yml", identifier="a", name="n")

    pack = load_pack(path.read_text(encoding="utf-8"))

    assert pack.corpus.notes == []
    assert pack.context == []
    assert pack.generated is None


def test_the_scaffold_shows_where_content_goes_without_declaring_it(
    tmp_path: Path,
):
    """A file with only an identity block tells an author nothing about what
    else a pack may hold. The sections are present as comments, which the
    parser ignores and a reader does not."""
    path = scaffold_pack(tmp_path / "p.ken.yml", identifier="a", name="n")

    text = path.read_text(encoding="utf-8")

    for section in ("literature", "docs", "notes", "context"):
        assert section in text
