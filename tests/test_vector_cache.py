"""Vectors kept between builds, so a rebuild embeds only what changed.

The cache is a dict persisted to disk, keyed on the full derivation binding.
It lives outside the index directory because that directory is replaced
wholesale by every build, and a cache inside it would be destroyed by the
very build it exists to make cheap.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kennis.engine.rag.binding import Binding, document_digest
from kennis.engine.rag.cache import VectorCache
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding


def a_binding(**overrides: object) -> Binding:
    parameters = overrides.get("chunking")
    model = overrides.get("model")
    return Binding(
        chunking=parameters
        if isinstance(parameters, ChunkParameters)
        else ChunkParameters(),
        model=model
        if isinstance(model, ModelBinding)
        else ModelBinding(kind="fastembed", model="bge-small", dim=4),
    )


def vectors(count: int = 3, value: float = 1.0) -> np.ndarray:
    return np.full((count, 4), value, dtype=np.float32)


@pytest.fixture
def cache(tmp_path: Path) -> VectorCache:
    return VectorCache(root=tmp_path / "vectors", binding=a_binding())


# ---------------------------------------------------------------------------
# Storing and reading back
# ---------------------------------------------------------------------------


def test_a_document_that_was_never_stored_is_a_miss(cache: VectorCache):
    assert cache.get("doc1", document_digest("text")) is None


def test_what_was_stored_comes_back(cache: VectorCache):
    digest = document_digest("text")
    cache.put("doc1", digest, vectors())

    stored = cache.get("doc1", digest)
    assert stored is not None
    assert np.array_equal(stored, vectors())


def test_the_vectors_survive_a_new_cache_over_the_same_directory(tmp_path: Path):
    """The point of the cache: a later process gets the earlier one's work."""
    digest = document_digest("text")
    VectorCache(root=tmp_path / "vectors", binding=a_binding()).put(
        "doc1", digest, vectors()
    )

    reopened = VectorCache(root=tmp_path / "vectors", binding=a_binding())
    assert reopened.get("doc1", digest) is not None


# ---------------------------------------------------------------------------
# What counts as a miss
# ---------------------------------------------------------------------------


def test_changed_text_is_a_miss(cache: VectorCache):
    cache.put("doc1", document_digest("old text"), vectors())

    assert cache.get("doc1", document_digest("new text")) is None


def test_another_document_is_a_miss(cache: VectorCache):
    digest = document_digest("text")
    cache.put("doc1", digest, vectors())

    assert cache.get("doc2", digest) is None


def test_changing_the_chunk_size_misses_every_document(tmp_path: Path):
    """The failure this prevents is silent: reusing vectors over the old
    chunk boundaries while BM25 is rebuilt over the new ones leaves the two
    indexes disagreeing about what a chunk is."""
    digest = document_digest("text")
    VectorCache(root=tmp_path / "vectors", binding=a_binding()).put(
        "doc1", digest, vectors()
    )

    changed = VectorCache(
        root=tmp_path / "vectors",
        binding=a_binding(chunking=ChunkParameters(size=800)),
    )
    assert changed.get("doc1", digest) is None


def test_changing_the_embedding_model_misses_every_document(tmp_path: Path):
    digest = document_digest("text")
    VectorCache(root=tmp_path / "vectors", binding=a_binding()).put(
        "doc1", digest, vectors()
    )

    changed = VectorCache(
        root=tmp_path / "vectors",
        binding=a_binding(
            model=ModelBinding(kind="fastembed", model="bge-large", dim=4)
        ),
    )
    assert changed.get("doc1", digest) is None


def test_a_miss_on_a_new_binding_does_not_destroy_the_old_one(tmp_path: Path):
    """Switching model and switching back should not have cost the work."""
    digest = document_digest("text")
    original = a_binding()
    VectorCache(root=tmp_path / "vectors", binding=original).put(
        "doc1", digest, vectors()
    )

    other = VectorCache(
        root=tmp_path / "vectors",
        binding=a_binding(
            model=ModelBinding(kind="fastembed", model="bge-large", dim=4)
        ),
    )
    other.put("doc1", digest, vectors(value=2.0))

    assert (
        VectorCache(root=tmp_path / "vectors", binding=original).get("doc1", digest)
        is not None
    )


# ---------------------------------------------------------------------------
# Only the changed document is recomputed
# ---------------------------------------------------------------------------


def test_adding_one_document_leaves_the_others_cached(cache: VectorCache):
    """The plan's test for this item, stated at the level the cache answers
    it: a rebuild asks the cache for each document, and only the new one is
    a miss."""
    first, second = document_digest("first"), document_digest("second")
    cache.put("doc1", first, vectors())
    cache.put("doc2", second, vectors())

    third = document_digest("third")
    misses = [
        identifier
        for identifier, digest in (("doc1", first), ("doc2", second), ("doc3", third))
        if cache.get(identifier, digest) is None
    ]

    assert misses == ["doc3"]


# ---------------------------------------------------------------------------
# Interrupt safety
# ---------------------------------------------------------------------------


def test_each_document_is_written_as_it_is_embedded(cache: VectorCache, tmp_path: Path):
    """Written per document so an interrupt loses at most the in-flight
    document's vectors rather than the run."""
    cache.put("doc1", document_digest("one"), vectors())

    assert list((tmp_path / "vectors").rglob("*.npy"))


def test_a_cache_root_that_does_not_exist_yet_is_created(tmp_path: Path):
    cache = VectorCache(root=tmp_path / "deep" / "vectors", binding=a_binding())

    cache.put("doc1", document_digest("one"), vectors())

    assert cache.get("doc1", document_digest("one")) is not None


def test_an_unreadable_entry_is_a_miss_rather_than_a_failure(
    cache: VectorCache, tmp_path: Path
):
    """A half-written file from an interrupted run must cost a recomputation,
    not the whole build."""
    cache.put("doc1", document_digest("one"), vectors())
    for path in (tmp_path / "vectors").rglob("*.npy"):
        path.write_bytes(b"not a numpy file")

    assert cache.get("doc1", document_digest("one")) is None


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


def test_pruning_drops_documents_that_are_no_longer_in_the_corpus(cache: VectorCache):
    cache.put("doc1", document_digest("one"), vectors())
    cache.put("doc2", document_digest("two"), vectors())

    cache.prune(keep={"doc1"})

    assert cache.get("doc1", document_digest("one")) is not None
    assert cache.get("doc2", document_digest("two")) is None


def test_pruning_drops_a_superseded_version_of_a_document_it_keeps(cache: VectorCache):
    """A document that has been edited several times leaves an entry per
    version, and only the current one is worth keeping."""
    cache.put("doc1", document_digest("old"), vectors())
    cache.put("doc1", document_digest("new"), vectors())

    cache.prune(keep={"doc1"}, digests={"doc1": document_digest("new")})

    assert cache.get("doc1", document_digest("new")) is not None
    assert cache.get("doc1", document_digest("old")) is None
