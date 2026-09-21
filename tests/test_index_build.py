"""Building an index and publishing it atomically.

Every piece from steps 1 to 3 meets here: the loader reads, the chunker cuts,
the cache answers what it already knows, the backend embeds the rest, and the
result is staged and swapped into place. The properties that matter are about
what happens when that is interrupted.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from kennis.engine.corpus.add import add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import NothingToIndex
from kennis.engine.rag.binding import Binding, document_digest
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding
from kennis.engine.rag.index import build_index, load_index
from kennis.engine.rag.loaders import CollectionLoader


class RecordingEmbedder:
    """Counts what it was asked to embed, so reuse is observable."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.embedded.extend(texts)
        # A vector that encodes its own text, so a row can be traced back.
        return np.array(
            [[float(len(text))] * self.dim for text in texts], dtype=np.float32
        )


@pytest.fixture
def notes(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="notes")


@pytest.fixture
def index_root(tmp_path: Path) -> Path:
    return tmp_path / "index"


def a_note(notes: Collection, tmp_path: Path, name: str, body: str) -> None:
    source = tmp_path / "sources" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    add_notes(notes, [str(source)])


def a_binding(**overrides: object) -> Binding:
    chunking = overrides.get("chunking")
    model = overrides.get("model")
    return Binding(
        chunking=chunking
        if isinstance(chunking, ChunkParameters)
        else ChunkParameters(),
        model=model
        if isinstance(model, ModelBinding)
        # `normalise=False` so the recording embedder's trick of encoding a
        # text's length in its vector survives: normalising every row of
        # `[n, n, ...]` yields the same unit vector whatever n was, which
        # would make row order unobservable.
        else ModelBinding(kind="fastembed", model="bge-small", dim=8, normalise=False),
    )


def build(
    notes: Collection,
    index_root: Path,
    *,
    binding: Binding | None = None,
    embedder: RecordingEmbedder | None = None,
) -> object:
    return build_index(
        CollectionLoader(notes),
        index_root=index_root,
        binding=binding or a_binding(),
        embedder=embedder or RecordingEmbedder(),
    )


# ---------------------------------------------------------------------------
# Refusing to build nothing
# ---------------------------------------------------------------------------


def test_an_empty_collection_says_the_collection_is_empty(
    notes: Collection, index_root: Path
):
    """Not `max() iterable argument is empty` from inside a vocabulary
    build, which names nothing the user can act on."""
    with pytest.raises(NothingToIndex) as raised:
        build(notes, index_root)

    assert "notes" in str(raised.value)


def test_refusing_writes_nothing_at_all(notes: Collection, index_root: Path):
    with pytest.raises(NothingToIndex):
        build(notes, index_root)

    assert not index_root.exists() or not list(index_root.rglob("*.jsonl"))


def test_documents_that_produce_no_chunks_are_refused_too(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """A different condition from an empty collection, and a different
    message: there are documents, and none of them has any text."""
    a_note(notes, tmp_path, "empty.md", "# \n\n   \n")
    for path in notes.path.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        head, _, _ = text.partition("\n---\n")
        path.write_text(f"{head}\n---\n\n   \n", encoding="utf-8")

    with pytest.raises(NothingToIndex):
        build(notes, index_root)


# ---------------------------------------------------------------------------
# What a build writes
# ---------------------------------------------------------------------------


def test_a_build_writes_an_index_that_can_be_loaded(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nA distinctive sentence.\n")

    build(notes, index_root)
    loaded = load_index(index_root, "notes")

    assert loaded.chunks
    assert any("distinctive" in chunk.text for chunk in loaded.chunks)


def test_the_binding_is_recorded_beside_the_index(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Plan item 3: so `corpus status` can report that the configuration and
    the index disagree, rather than silently recomputing."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    report = build(notes, index_root)
    recorded = json.loads(
        (Path(report.index_dir) / "binding.json").read_text(encoding="utf-8")
    )

    assert recorded["digest"] == a_binding().digest
    assert recorded["chunk_size"] == 1500
    assert recorded["embedding_model"] == "bge-small"


def test_the_manifest_records_what_was_indexed(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    report = build(notes, index_root)
    manifest = json.loads(
        (Path(report.index_dir) / "manifest.json").read_text(encoding="utf-8")
    )

    held = notes.contents().documents[0]
    assert manifest["collection"] == "notes"
    assert manifest["documents"][held.id] == document_digest(held.body)
    assert manifest["chunk_count"] == report.chunk_count


def test_the_matrix_has_one_row_per_chunk(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """A rank is a position in the chunk list, so a matrix of a different
    height means every dense hit points at the wrong chunk."""
    a_note(notes, tmp_path, "one.md", "# One\n\n" + ("word " * 800))
    a_note(notes, tmp_path, "two.md", "# Two\n\nShort.\n")

    build(notes, index_root)
    loaded = load_index(index_root, "notes")

    assert loaded.matrix is not None
    assert loaded.matrix.shape[0] == len(loaded.chunks)


def test_row_order_matches_chunk_order_across_cached_and_fresh_documents(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The invariant the whole cache rests on: whatever mixture of hits and
    misses produced the matrix, row i belongs to chunk i."""
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body here.\n")
    build(notes, index_root)

    a_note(notes, tmp_path, "two.md", "# Two\n\nA much longer second body here.\n")
    build(notes, index_root)

    loaded = load_index(index_root, "notes")
    assert loaded.matrix is not None
    for row, chunk in zip(loaded.matrix, loaded.chunks, strict=True):
        assert float(row[0]) == float(len(chunk.text))


# ---------------------------------------------------------------------------
# Reuse
# ---------------------------------------------------------------------------


def test_rebuilding_an_unchanged_collection_embeds_nothing(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")
    build(notes, index_root)

    second = RecordingEmbedder()
    build(notes, index_root, embedder=second)

    assert second.embedded == []


def test_adding_one_document_re_embeds_one_document(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The plan's test for the cache, end to end."""
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")
    build(notes, index_root)

    a_note(notes, tmp_path, "three.md", "# Three\n\nThird body.\n")
    second = RecordingEmbedder()
    build(notes, index_root, embedder=second)

    assert len(second.embedded) == 1
    assert "Third body." in second.embedded[0]


def test_editing_a_document_re_embeds_only_that_document(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")
    build(notes, index_root)

    edited = sorted(notes.path.glob("*.md"))[0]
    edited.write_text(
        edited.read_text(encoding="utf-8").replace("body.", "body, revised."),
        encoding="utf-8",
    )
    second = RecordingEmbedder()
    build(notes, index_root, embedder=second)

    assert len(second.embedded) == 1


def test_changing_the_chunk_size_re_embeds_everything(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")
    build(notes, index_root)

    second = RecordingEmbedder()
    build(
        notes,
        index_root,
        binding=a_binding(chunking=ChunkParameters(size=400)),
        embedder=second,
    )

    assert len(second.embedded) == 2


def test_changing_the_embedding_model_re_embeds_everything(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")
    build(notes, index_root)

    second = RecordingEmbedder()
    build(
        notes,
        index_root,
        binding=a_binding(
            model=ModelBinding(kind="fastembed", model="bge-large", dim=8)
        ),
        embedder=second,
    )

    assert len(second.embedded) == 2


# ---------------------------------------------------------------------------
# Publishing, and being interrupted
# ---------------------------------------------------------------------------


def test_the_pointer_names_the_index_that_was_built(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    report = build(notes, index_root)
    pointer = json.loads(
        (index_root / "notes" / "latest.json").read_text(encoding="utf-8")
    )

    assert pointer["index_id"] == report.index_id


def test_an_interrupted_build_leaves_the_previous_index_serving(
    notes: Collection, tmp_path: Path, index_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """Deleting the previous index first meant a Ctrl-C partway through left
    the collection with no index at all - strictly worse than never having
    run the command."""
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    build(notes, index_root)
    before = [chunk.text for chunk in load_index(index_root, "notes").chunks]

    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")

    class Interrupting:
        def embed(self, texts: list[str]) -> np.ndarray:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        build_index(
            CollectionLoader(notes),
            index_root=index_root,
            binding=a_binding(),
            embedder=Interrupting(),
        )

    assert [chunk.text for chunk in load_index(index_root, "notes").chunks] == before


def test_an_interrupted_build_leaves_no_staging_directory(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")
    build(notes, index_root)

    class Interrupting:
        def embed(self, texts: list[str]) -> np.ndarray:
            raise KeyboardInterrupt

    a_note(notes, tmp_path, "two.md", "# Two\n\nBody.\n")
    with pytest.raises(KeyboardInterrupt):
        build_index(
            CollectionLoader(notes),
            index_root=index_root,
            binding=a_binding(),
            embedder=Interrupting(),
        )

    staging = [
        path for path in (index_root / "notes").iterdir() if ".staging" in path.name
    ]
    assert staging == []


def test_the_pointer_is_not_written_before_the_swap(
    notes: Collection, tmp_path: Path, index_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """The one ordering that could serve a half-built index.

    The failure has to be placed *inside* the staging block to test this at
    all. Interrupting during embedding proves only that the pointer is not
    written before embedding, which is a much weaker claim and was what an
    earlier version of this test actually checked.
    """
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")

    def fail_while_staging(texts: list[str]) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "kennis.engine.rag.index.Bm25Index.build", staticmethod(fail_while_staging)
    )

    with pytest.raises(KeyboardInterrupt):
        build_index(
            CollectionLoader(notes),
            index_root=index_root,
            binding=a_binding(),
            embedder=RecordingEmbedder(),
        )

    assert not (index_root / "notes" / "latest.json").exists()


def test_a_failure_while_staging_leaves_the_previous_pointer_untouched(
    notes: Collection, tmp_path: Path, index_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """And the second half: a rebuild that dies mid-staging must leave the
    pointer naming the index that is still there and still complete."""
    a_note(notes, tmp_path, "one.md", "# One\n\nBody.\n")
    build(notes, index_root)
    pointer = (index_root / "notes" / "latest.json").read_text(encoding="utf-8")

    a_note(notes, tmp_path, "two.md", "# Two\n\nBody.\n")

    def fail_while_staging(texts: list[str]) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "kennis.engine.rag.index.Bm25Index.build", staticmethod(fail_while_staging)
    )
    with pytest.raises(KeyboardInterrupt):
        build(notes, index_root)

    assert (index_root / "notes" / "latest.json").read_text(encoding="utf-8") == pointer
    assert load_index(index_root, "notes").chunks


def test_an_interrupted_build_keeps_the_vectors_it_had_already_computed(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """Section 15: a build that aborts leaves cached vectors for an index
    that was never published, and that is the point - the next attempt starts
    from them."""
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")

    class FailingAfterFirst:
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, texts: list[str]) -> np.ndarray:
            self.calls += 1
            if self.calls > 1:
                raise KeyboardInterrupt
            return np.array([[1.0] * 8 for _ in texts], dtype=np.float32)

    with pytest.raises(KeyboardInterrupt):
        build_index(
            CollectionLoader(notes),
            index_root=index_root,
            binding=a_binding(),
            embedder=FailingAfterFirst(),
            embed_batch_size=1,
        )

    assert list((index_root / "notes" / "vectors").rglob("*.npy"))


# ---------------------------------------------------------------------------
# Keeping the cache bounded
# ---------------------------------------------------------------------------


def test_a_removed_document_loses_its_cached_vectors(
    notes: Collection, tmp_path: Path, index_root: Path
):
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    a_note(notes, tmp_path, "two.md", "# Two\n\nSecond body.\n")
    build(notes, index_root)
    cached = len(list((index_root / "notes" / "vectors").rglob("*.npy")))

    notes.remove(notes.contents().documents[0])
    build(notes, index_root)

    assert len(list((index_root / "notes" / "vectors").rglob("*.npy"))) < cached


def test_an_edited_document_loses_its_superseded_vectors(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """The faster of the two kinds of growth: a document edited several times
    leaves one entry per version it ever had."""
    a_note(notes, tmp_path, "one.md", "# One\n\nFirst body.\n")
    build(notes, index_root)

    edited = sorted(notes.path.glob("*.md"))[0]
    edited.write_text(
        edited.read_text(encoding="utf-8").replace("First body.", "Revised body."),
        encoding="utf-8",
    )
    build(notes, index_root)

    assert len(list((index_root / "notes" / "vectors").rglob("*.npy"))) == 1


# ---------------------------------------------------------------------------
# A lexical-only index
# ---------------------------------------------------------------------------


def test_a_collection_can_be_indexed_with_no_embedding_backend(
    notes: Collection, tmp_path: Path, index_root: Path
):
    """A machine with no model must still be able to search, and the plan
    calls BM25 the pure-text path."""
    a_note(notes, tmp_path, "one.md", "# One\n\nA distinctive sentence.\n")

    build_index(
        CollectionLoader(notes),
        index_root=index_root,
        binding=Binding(chunking=ChunkParameters(), model=None),
    )
    loaded = load_index(index_root, "notes")

    assert loaded.chunks
    assert loaded.matrix is None
