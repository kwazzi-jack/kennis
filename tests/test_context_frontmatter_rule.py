"""A bundle file is indexed only when it has a frontmatter header, unless
the project says otherwise (Brian, 2026-11-06, #624).

A header is what makes a file a note kennis can describe - its title, who
owns it - so a markdown file without one (a README, an export) stays in the
project and out of its search. `bundle.json`'s `index_without_frontmatter`
puts every file back in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kennis.engine.context.bundle import MANIFEST_FILENAME, init_bundle
from kennis.engine.context.index import BundleLoader
from kennis.engine.context.notes import indexed_documents
from kennis.engine.context.status import bundle_status


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    created = init_bundle(project).path
    (created / "headed.md").write_text(
        "---\ntitle: Headed\n---\nCalibration runs nightly.\n", encoding="utf-8"
    )
    (created / "plain.md").write_text("Imaging runs weekly.\n", encoding="utf-8")
    (created / "broken.md").write_text(
        "---\ntitle: [unclosed\n---\nBroken.\n", encoding="utf-8"
    )
    (created / "empty.md").write_text("---\n---\nEmpty header.\n", encoding="utf-8")
    return created


def names(paths: list[Path]) -> list[str]:
    return sorted(path.name for path in paths)


def test_only_a_file_with_a_header_is_indexed(bundle: Path):
    assert names(indexed_documents(bundle)) == ["headed.md"]
    assert [document.id for document in BundleLoader(bundle).documents()] == [
        "headed.md"
    ]


def test_init_writes_the_setting_so_it_can_be_found(bundle: Path):
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["index_without_frontmatter"] is False


def test_the_project_can_index_every_file(bundle: Path):
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["index_without_frontmatter"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert names(indexed_documents(bundle)) == [
        "broken.md",
        "empty.md",
        "headed.md",
        "plain.md",
    ]


def test_a_bundle_made_before_the_setting_indexes_headed_files_only(bundle: Path):
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["index_without_frontmatter"]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert names(indexed_documents(bundle)) == ["headed.md"]


def test_status_names_what_is_left_out_and_why(bundle: Path):
    status = bundle_status(bundle)

    assert status.document_count == 1
    assert status.without_frontmatter == ("empty.md", "plain.md")
    assert status.unreadable == ("broken.md",)
