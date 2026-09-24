"""The derivation binding: everything that decides what a vector is.

The point of carrying the whole binding rather than the obvious shorter key
is a silent failure. Key on content and model alone, then change the chunk
size: every document is a cache *hit*, so the dense index is reused over the
old chunk boundaries while BM25 is rebuilt over the new ones. The two then
disagree about what chunk seven is, and every offset, span and fused rank is
computed against mismatched lists. Nothing errors.
"""

from __future__ import annotations

from kennis.engine.rag.binding import Binding, binding_from, document_digest
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding, reachable_model
from kennis.engine.settings import ChunkingSettings, EmbeddingSettings


def a_binding(
    *,
    parameters: ChunkParameters | None = None,
    model: ModelBinding | None = None,
) -> Binding:
    return Binding(
        chunking=parameters or ChunkParameters(),
        model=model or ModelBinding(kind="fastembed", model="bge-small", dim=384),
    )


def test_the_same_binding_digests_the_same_way():
    assert a_binding().digest == a_binding().digest


def test_the_digest_is_stable_across_processes():
    """A cache written by one run has to be readable by the next, so the
    digest cannot depend on anything the interpreter chooses per process."""
    assert a_binding().digest == (
        Binding(
            chunking=ChunkParameters(),
            model=ModelBinding(kind="fastembed", model="bge-small", dim=384),
        ).digest
    )


# ---------------------------------------------------------------------------
# Everything in the binding changes the digest
# ---------------------------------------------------------------------------


def test_a_different_chunk_size_is_a_different_binding():
    assert a_binding().digest != a_binding(parameters=ChunkParameters(size=800)).digest


def test_a_different_overlap_is_a_different_binding():
    assert (
        a_binding().digest != a_binding(parameters=ChunkParameters(overlap=50)).digest
    )


def test_a_different_chunker_version_is_a_different_binding():
    """A changed packing algorithm with unchanged parameters produces
    different chunks, so the version has to count."""
    assert a_binding().digest != a_binding(parameters=ChunkParameters(version=2)).digest


def test_a_different_backend_is_a_different_binding():
    assert (
        a_binding().digest
        != a_binding(
            model=ModelBinding(
                kind="ollama", model="bge-small", host="http://h", dim=384
            )
        ).digest
    )


def test_a_different_model_is_a_different_binding():
    assert (
        a_binding().digest
        != a_binding(
            model=ModelBinding(kind="fastembed", model="bge-large", dim=384)
        ).digest
    )


def test_a_different_dimension_is_a_different_binding():
    assert (
        a_binding().digest
        != a_binding(
            model=ModelBinding(kind="fastembed", model="bge-small", dim=768)
        ).digest
    )


def test_a_different_normalisation_is_a_different_binding():
    """Vectors normalised and not normalised are not comparable, and the
    difference is invisible in the numbers themselves."""
    assert (
        a_binding().digest
        != a_binding(
            model=ModelBinding(
                kind="fastembed", model="bge-small", dim=384, normalise=False
            )
        ).digest
    )


def test_the_host_does_not_change_the_binding():
    """Where a model was reached from does not change what it computes, and
    keying on it would miss the cache every time a daemon moved port."""
    assert (
        a_binding(
            model=ModelBinding(
                kind="ollama", model="bge-small", host="http://one:11434", dim=384
            )
        ).digest
        == a_binding(
            model=ModelBinding(
                kind="ollama", model="bge-small", host="http://two:11434", dim=384
            )
        ).digest
    )


def test_concurrency_does_not_change_the_binding():
    """How many requests were in flight is not part of what a vector is."""
    assert (
        a_binding(
            model=ModelBinding(
                kind="fastembed", model="bge-small", dim=384, max_async=2
            )
        ).digest
        == a_binding(
            model=ModelBinding(
                kind="fastembed", model="bge-small", dim=384, max_async=16
            )
        ).digest
    )


# ---------------------------------------------------------------------------
# The document digest
# ---------------------------------------------------------------------------


def test_the_same_text_digests_the_same_way():
    assert document_digest("some text") == document_digest("some text")


def test_different_text_digests_differently():
    assert document_digest("some text") != document_digest("some other text")


def test_the_digest_is_of_the_text_and_nothing_else():
    """Whitespace is content to a chunker: it decides block boundaries, so a
    digest that ignored it would claim two different chunk lists are one."""
    assert document_digest("a\n\nb") != document_digest("a\nb")


# ---------------------------------------------------------------------------
# What the binding says about itself
# ---------------------------------------------------------------------------


def test_a_binding_round_trips_through_its_recorded_form():
    """Step 4 writes this to `index/binding.json` so `corpus status` can say
    the configuration and the index disagree, rather than recomputing."""
    binding = a_binding()

    assert Binding.from_recorded(binding.recorded()) == binding


def test_the_recorded_form_names_its_fields():
    """It is read by a person looking at an index directory, so it holds
    names rather than one opaque digest."""
    recorded = a_binding().recorded()

    assert recorded["embedding_model"] == "bge-small"
    assert recorded["chunk_size"] == 1500
    assert recorded["digest"] == a_binding().digest


# ---------------------------------------------------------------------------
# What the stored binding is, and what it is not
# ---------------------------------------------------------------------------


def test_the_stored_binding_does_not_record_where_the_backend_lives():
    """A binding says **what the vectors are**, not how to reach the thing
    that made them. Two machines reaching the same ollama at different
    addresses hold the same index, so an address in the binding would make
    them disagree about a shared artefact.

    This is also why a query has to be embedded with the stored identity and
    the *current* host: reading the host back off the binding gets None, and
    `validate_binding` then refuses every ollama search. Concern #210.
    """
    stored = binding_from(
        ChunkingSettings(),
        EmbeddingSettings(
            backend="ollama",
            model="nomic-embed-text",
            dimensions=768,
            base_url="http://localhost:11434",
        ),
    )

    written = stored.recorded()

    assert "host" not in written
    assert "http://localhost:11434" not in str(written)


def test_a_stored_binding_takes_a_runtime_host_for_the_query():
    """The merge: identity from disk, connection from configuration."""
    stored = binding_from(
        ChunkingSettings(),
        EmbeddingSettings(backend="ollama", model="nomic-embed-text", dimensions=768),
    )
    assert stored.model is not None

    reachable = reachable_model(stored.model, host="http://elsewhere:11434")

    assert reachable.host == "http://elsewhere:11434"
    assert reachable.model == stored.model.model
    assert reachable.dim == stored.model.dim
    assert reachable.normalise == stored.model.normalise


def test_a_runtime_host_of_none_leaves_the_binding_alone():
    """fastembed has no host and must not acquire one."""
    stored = binding_from(
        ChunkingSettings(),
        EmbeddingSettings(backend="fastembed", model="m", dimensions=8),
    )
    assert stored.model is not None

    assert reachable_model(stored.model, host=None) == stored.model
