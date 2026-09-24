"""Reading a corpus collection into documents the retrieval stack can use.

The loader is the only part of the retrieval stack that knows what a corpus
looks like. Everything downstream works on `rag.Document`, which is why the
context bundle will be able to use the same engine later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.corpus.add import AddOptions, add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.events import Recorder, Severity
from kennis.engine.rag.loaders import CollectionLoader


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="notes")


def a_note(notes: Collection, tmp_path: Path, name: str, body: str) -> None:
    source = tmp_path / "sources" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    add_notes(notes, [str(source)])


def loaded(collection: Collection) -> list[object]:
    return list(CollectionLoader(collection).documents())


# ---------------------------------------------------------------------------
# What a document carries
# ---------------------------------------------------------------------------


def test_every_document_in_the_collection_is_loaded(notes: Collection, tmp_path: Path):
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")

    assert len(loaded(notes)) == 2


def test_the_text_is_the_body_without_the_frontmatter(
    notes: Collection, tmp_path: Path
):
    """Frontmatter is metadata to filter on, not text to retrieve: indexing
    it would match a query against a document's own identifier."""
    a_note(notes, tmp_path, "one.md", "# One\n\nA distinctive sentence.\n")

    document = CollectionLoader(notes).documents()[0]

    assert "A distinctive sentence." in document.text
    assert "schema_version" not in document.text
    assert document.id not in document.text


def test_the_identifier_is_the_documents_own(notes: Collection, tmp_path: Path):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    held = notes.contents().documents[0]
    assert CollectionLoader(notes).documents()[0].id == held.id


# ---------------------------------------------------------------------------
# Provenance that survives the corpus moving
# ---------------------------------------------------------------------------


def test_the_source_path_is_relative_to_the_corpus_root(
    notes: Collection, tmp_path: Path
):
    """Concern #52. An absolute path here makes every chunk in the index
    point at nothing the moment the corpus is moved, cloned to another
    machine, or restored from a backup - while the documents are fine."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    source_path = CollectionLoader(notes).documents()[0].source_path

    assert not Path(source_path).is_absolute()
    assert source_path.startswith("notes/")
    assert (notes.root / source_path).is_file()


def test_the_source_path_uses_forward_slashes(notes: Collection, tmp_path: Path):
    """It is stored and compared as text, so it must not depend on which
    platform wrote the index."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    assert "\\" not in CollectionLoader(notes).documents()[0].source_path


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_a_document_at_the_collection_root_has_no_group(
    notes: Collection, tmp_path: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    assert CollectionLoader(notes).documents()[0].metadata["group"] == ""


def test_a_grouped_document_records_its_group(notes: Collection, tmp_path: Path):
    source = tmp_path / "sources" / "one.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# One\n\nBody.\n", encoding="utf-8")
    add_notes(notes, [str(source)], AddOptions(group="calibration/gains"))

    assert (
        CollectionLoader(notes).documents()[0].metadata["group"] == "calibration/gains"
    )


def test_the_group_is_recorded_rather_than_derived_at_query_time(
    notes: Collection, tmp_path: Path
):
    """A wrapped document's group is its wrapper's parent, not its file's
    parent, so re-deriving it from a path would put layout knowledge into the
    query layer."""
    source = tmp_path / "sources" / "paper.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Paper\n\nBody.\n", encoding="utf-8")
    add_notes(notes, [str(source)], AddOptions(group="imaging"))

    document = CollectionLoader(notes).documents()[0]
    assert document.metadata["group"] == "imaging"


# ---------------------------------------------------------------------------
# Metadata the filters read
# ---------------------------------------------------------------------------


def test_the_frontmatter_is_reachable_by_its_own_field_names(
    notes: Collection, tmp_path: Path
):
    """Step 1's filters take a dotted path because kennis namespaces its
    per-collection fields into a block. The two were designed against each
    other, so the metadata has to arrive with those names."""
    # Named `A Title.md` rather than headed `# A Title`: since #189 a note
    # from a file is titled by its filename, and what this test is about is
    # that the title reaches the metadata at all.
    a_note(notes, tmp_path, "A Title.md", "# A Title\n\nBody.\n")

    metadata = CollectionLoader(notes).documents()[0].metadata

    assert metadata["title"] == "A Title"
    assert metadata["owner"] == "user"
    assert "source" in metadata


def test_a_literature_document_exposes_its_bibliography(tmp_path: Path):
    import httpx

    from kennis.engine.corpus.add import add_literature

    papers = Collection(root=tmp_path / "corpus", name="literature")
    # The entry names its document. A literature document is a paper's text
    # or it is not written, so a bibliography with no `file =` field and no
    # eprint is refused whole and this loader would have nothing to read.
    document = tmp_path / "paper.md"
    document.write_text("# A Title\n\nThe paper's text.\n", encoding="utf-8")
    bib = tmp_path / "library.bib"
    bib.write_text(
        f"@article{{smirnov2011,\n title={{A Title}},\n year={{2011}},\n"
        f" doi={{10.1051/0004-6361/201016082}},\n file={{{document}}}\n}}\n",
        encoding="utf-8",
    )

    def offline(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    add_literature(
        papers,
        [str(bib)],
        AddOptions(request_delay_seconds=0),
        arxiv=httpx.Client(transport=httpx.MockTransport(offline)),
    )

    metadata = CollectionLoader(papers).documents()[0].metadata
    assert metadata["bib"]["citekey"] == "smirnov2011"
    assert metadata["bib"]["year"] == "2011"


# ---------------------------------------------------------------------------
# A document that cannot be read
# ---------------------------------------------------------------------------


def test_a_document_that_cannot_be_read_does_not_stop_the_others(
    notes: Collection, tmp_path: Path
):
    """Milestone 2 spent two commits learning this: one hand-edited note must
    not cost every other operation."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nBody.\n")
    broken = sorted(notes.path.glob("*.md"))[0]
    broken.write_text("---\nnot: valid frontmatter\n---\n\nBody.\n", encoding="utf-8")

    assert len(loaded(notes)) == 1


def test_a_document_that_cannot_be_read_is_reported(notes: Collection, tmp_path: Path):
    """It must not vanish silently either: a document the user will not find
    when searching is exactly what they would want told."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")
    broken = sorted(notes.path.glob("*.md"))[0]
    broken.write_text("---\nnot: valid frontmatter\n---\n\nBody.\n", encoding="utf-8")

    recorder = Recorder()
    CollectionLoader(notes).documents(events=recorder)

    diagnostics = [
        event for event in recorder.events if getattr(event, "severity", None)
    ]
    assert diagnostics
    assert any(event.severity is Severity.WARNING for event in diagnostics)


def test_an_empty_collection_loads_nothing_rather_than_failing(notes: Collection):
    """Refusing is the index build's job, and it has a better message for it
    than the loader could."""
    assert loaded(notes) == []


# ---------------------------------------------------------------------------
# The loader's identity
# ---------------------------------------------------------------------------


def test_the_loader_is_named_for_its_collection(notes: Collection):
    assert CollectionLoader(notes).name == "notes"


def test_the_metadata_can_be_written_to_the_index(notes: Collection, tmp_path: Path):
    """Chunks are written to the index as JSON, and a chunk carries its
    document's metadata. `source.at` is a datetime in the validated model, so
    dumping the model without asking for JSON types puts an object in there
    that only fails much later, in step 4, far from its cause."""
    import json

    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    metadata = CollectionLoader(notes).documents()[0].metadata

    json.dumps(metadata)


def test_a_timestamp_arrives_as_text(notes: Collection, tmp_path: Path):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    recorded = CollectionLoader(notes).documents()[0].metadata["source"]["at"]

    assert isinstance(recorded, str)
