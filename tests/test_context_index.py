"""Indexing a `.context/` bundle with the corpus's own retrieval engine.

The point of these is that there is no second retrieval implementation:
`BundleLoader` satisfies the same `Loader` protocol `CollectionLoader` does,
and everything downstream - chunking, BM25, the index writer, search - is
reached unchanged. So what is tested here is the loader's reading of a
bundle and the three things a bundle index does differently from a corpus
one: no repository, no embedding leg, and a path for an identifier.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kennis.engine.context import (
    BundleLoader,
    index_bundle,
    index_root_for,
    init_bundle,
    load_bundle_index,
    remember_in_bundle,
)
from kennis.engine.errors import NothingToIndex
from kennis.engine.events import Diagnostic, Recorder, Severity
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.index import load_index, read_manifest
from kennis.engine.rag.search import search


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return init_bundle(tmp_path / "project").path


def a_file(bundle: Path, relative: str, text: str) -> Path:
    path = bundle / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# What the loader reads
# ---------------------------------------------------------------------------


def test_a_documents_identity_is_its_path(bundle: Path):
    """A bundle has no surrogate identifiers and must not gain any: a hit's
    handle is the file path, because the file is the user's own."""
    a_file(bundle, "conventions/naming.md", "Names are lowercase.\n")

    documents = BundleLoader(bundle).documents()

    assert [document.id for document in documents] == ["conventions/naming.md"]
    assert [document.source_path for document in documents] == ["conventions/naming.md"]
    assert documents[0].base_path is None


def test_the_landing_file_and_dotted_paths_are_not_documents(bundle: Path):
    a_file(bundle, "kept.md", "Keep this.\n")
    a_file(bundle, ".hidden.md", "Not this.\n")
    a_file(bundle, ".index/context/leftover.md", "Nor this.\n")

    assert [document.id for document in BundleLoader(bundle).documents()] == ["kept.md"]


def test_the_group_is_the_directory_the_file_sits_in(bundle: Path):
    """`CollectionLoader` records `group` so a filter does not have to
    re-derive it from the path. The bundle records the same key."""
    a_file(bundle, "decisions/solver.md", "Quartical.\n")
    a_file(bundle, "root.md", "At the top.\n")

    groups = {
        document.id: document.metadata["group"]
        for document in BundleLoader(bundle).documents()
    }

    assert groups == {"decisions/solver.md": "decisions", "root.md": ""}


def test_frontmatter_becomes_metadata(bundle: Path):
    a_file(
        bundle,
        "naming.md",
        "---\ntitle: Naming\ndescription: How things are named.\nowner: user\n---\n\n"
        "Names are lowercase.\n",
    )

    document = BundleLoader(bundle).documents()[0]

    assert document.metadata["title"] == "Naming"
    assert document.metadata["description"] == "How things are named."
    assert document.metadata["owner"] == "user"
    assert document.text.strip() == "Names are lowercase."


def test_a_file_with_no_frontmatter_is_a_document_and_not_a_complaint(bundle: Path):
    """A user writes a file by hand without the block. That is a file with
    no metadata, not a broken file, and the whole of it is its text."""
    a_file(bundle, "jotting.md", "# Jotting\n\nNames are lowercase.\n")
    events = Recorder()

    documents = BundleLoader(bundle).documents(events=events)

    assert documents[0].text == "# Jotting\n\nNames are lowercase.\n"
    assert documents[0].metadata["title"] == "jotting"
    assert events.events_of_type(Diagnostic) == []


def test_frontmatter_that_does_not_parse_is_reported_and_the_body_kept(bundle: Path):
    """Three ways to have a block that yields nothing - unterminated, not a
    mapping, and not YAML at all - and one statement covers them: something
    here looks like frontmatter and none of it was read. The file is still
    indexed, because dropping a user's file over its header would lose the
    text they wanted found."""
    a_file(bundle, "broken.md", "---\ntitle: [unclosed\n---\n\nNames are lowercase.\n")
    events = Recorder()

    documents = BundleLoader(bundle).documents(events=events)

    assert [document.id for document in documents] == ["broken.md"]
    assert "Names are lowercase." in documents[0].text
    warnings = [
        event
        for event in events.events_of_type(Diagnostic)
        if event.severity is Severity.WARNING
    ]
    assert len(warnings) == 1
    assert "broken.md" in warnings[0].message


# ---------------------------------------------------------------------------
# What the build does differently from a corpus build
# ---------------------------------------------------------------------------


def test_indexing_a_bundle_makes_it_searchable(bundle: Path):
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")

    report = index_bundle(bundle)

    assert report.chunk_count >= 1
    loaded = load_index(index_root_for(bundle), "context")
    hits = search(loaded, "calibration chunks", top_k=3, mode="bm25")
    assert hits
    assert hits[0].chunk.source_path.endswith(".md")


def test_the_index_has_no_embedding_leg_and_leaves_no_cache(bundle: Path):
    """BM25-only is the design's choice for a bundle: a hybrid index turns
    `context init` from an offline scaffold into a model download. The cache
    directory is the observable consequence - it is written by `put`, so a
    build that never embeds must not create one."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")

    index_bundle(bundle)

    loaded = load_index(index_root_for(bundle), "context")
    assert loaded.matrix is None
    assert not (index_root_for(bundle) / "context" / "vectors").exists()


def test_the_manifest_records_no_commit_and_every_documents_digest(bundle: Path):
    """kennis does not own this repository, so it cannot record a commit to
    diff freshness against. The digests are what `context status` compares
    instead, and recording none of them would leave it nothing to read."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    a_file(bundle, "second.md", "Another thing.\n")

    index_bundle(bundle)

    manifest = read_manifest(index_root_for(bundle), "context")
    assert manifest is not None
    assert manifest.built_from is None
    assert set(manifest.documents) == {
        document.id for document in BundleLoader(bundle).documents()
    }


def test_an_empty_bundle_is_refused_with_something_to_do_about_it(bundle: Path):
    """A freshly scaffolded bundle holds only the landing file and the
    skeleton, both excluded, so this is the first thing a new user meets."""
    with pytest.raises(NothingToIndex) as raised:
        index_bundle(bundle)

    assert "kennis remember" in "".join(raised.value.__notes__)


def test_an_index_moved_to_another_path_is_searchable_without_rebuilding(
    bundle: Path, tmp_path: Path
):
    """Nothing in the index may name the path it was built at.

    This used to be justified by the clone: a committed index had to work
    wherever the clone landed. The index is no longer committed (#248), and
    the property survives the reason for it - a workspace gets renamed,
    moved between machines, or restored from a backup, and an index full of
    absolute paths would point at nothing while the documents were fine.
    """
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)

    moved = tmp_path / "moved" / ".context"
    moved.parent.mkdir(parents=True)
    shutil.copytree(bundle, moved)
    # Removed, so nothing at the new path can be resolving against the old
    # one. Copying alone would let an index full of absolute paths pass.
    shutil.rmtree(bundle)

    loaded = load_index(index_root_for(moved), "context")
    hits = search(loaded, "calibration chunks", top_k=3, mode="bm25")
    assert hits
    assert not Path(hits[0].chunk.source_path).is_absolute()


def test_the_published_binding_records_the_chunking_it_was_built_with(bundle: Path):
    """What makes a committed index checkable on another machine. The index
    directory is named after the embedding model alone - `index_id_for` says
    so, and for a lexical index that is the constant `bm25` - so the chunk
    parameters live in `binding.json` and nowhere else. A reader that cannot
    find them there has no way to know the index it was handed disagrees
    with its own settings."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks. " * 40)

    first = index_bundle(bundle, chunking=ChunkParameters(size=400, overlap=40))
    second = index_bundle(bundle, chunking=ChunkParameters(size=900, overlap=40))

    assert first.chunk_count > second.chunk_count
    recorded = json.loads(
        (second.index_dir / "binding.json").read_text(encoding="utf-8")
    )
    assert recorded["chunk_size"] == 900
    assert recorded["chunk_overlap"] == 40
    assert load_index(index_root_for(bundle), "context").binding.chunking.size == 900


def test_a_bundle_with_no_index_names_the_command_that_builds_one(bundle: Path):
    """`load_index` names `kennis corpus index --collection <name>`, which is
    the right command for a corpus collection and not a command at all for a
    bundle - `context` is not one of the three the option accepts. Rule 4.4
    says a printed command runs as printed, so the bundle reader translates
    it."""
    with pytest.raises(NothingToIndex) as raised:
        load_bundle_index(bundle)

    notes = "".join(raised.value.__notes__)
    assert "kennis context index" in notes
    assert "corpus index" not in notes


def test_a_file_whose_frontmatter_does_not_parse_does_not_break_remembering(
    bundle: Path,
):
    """`remember --context` scans every file's body to deduplicate, so one
    hand-broken header in the bundle must not take the write path down with
    it."""
    a_file(bundle, "broken.md", "---\ntitle: [unclosed\n---\n\nSomething else.\n")

    note = remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")

    assert note.path.is_file()
