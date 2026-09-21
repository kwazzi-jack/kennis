"""Turning text into vectors, through whichever backend is configured.

Nothing here downloads a model. Every test supplies its own embedder, which
is the seam the engine needs anyway: the backend is named by a binding and
resolved at the edge, so a caller with no network - a test, an offline run -
hands over one that says so.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from kennis.engine.errors import EmbeddingUnavailable, SettingsError
from kennis.engine.rag.embedding import (
    ModelBinding,
    embed_texts,
    resolve_host,
    validate_binding,
)


class CountingEmbedder:
    """An embedder that records what it was asked, in order."""

    def __init__(self, dim: int = 4, delay: float = 0.0) -> None:
        self.dim = dim
        self.delay = delay
        self.batches: list[list[str]] = []
        self._lock = threading.Lock()
        self.peak_in_flight = 0
        self._in_flight = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            self.batches.append(list(texts))
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self._in_flight -= 1
        # A vector that encodes its own text, so row order is checkable.
        return np.array(
            [[float(len(text))] * self.dim for text in texts], dtype=np.float32
        )


def a_binding(**overrides: object) -> ModelBinding:
    fields: dict[str, object] = {
        "kind": "fastembed",
        "model": "bge-small",
        "dim": 4,
    }
    fields.update(overrides)
    return ModelBinding(
        kind=str(fields["kind"]),
        model=str(fields["model"]),
        dim=int(str(fields["dim"])),
        host=fields.get("host") if isinstance(fields.get("host"), str) else None,
        normalise=bool(fields.get("normalise", True)),
        max_async=int(str(fields["max_async"])) if "max_async" in fields else None,
    )


# ---------------------------------------------------------------------------
# Shape and order
# ---------------------------------------------------------------------------


def test_embedding_produces_one_row_per_text():
    matrix = embed_texts(
        a_binding(normalise=False), ["one", "two", "three"], embedder=CountingEmbedder()
    )

    assert matrix.shape == (3, 4)
    assert matrix.dtype == np.float32


def test_row_order_matches_input_order_whatever_order_batches_finish_in():
    """Batches run concurrently, so the only thing keeping a vector attached
    to its text is that results are placed by index rather than appended."""
    texts = [f"text of length {index:03d}" + "x" * index for index in range(200)]

    matrix = embed_texts(
        a_binding(normalise=False), texts, embedder=CountingEmbedder(), batch_size=8
    )

    assert [float(row[0]) for row in matrix] == [float(len(text)) for text in texts]


def test_no_texts_produces_an_empty_matrix_of_the_right_width():
    """Shaped rather than empty, so a caller can stack it without a special
    case for the collection that had nothing in it."""
    matrix = embed_texts(a_binding(), [], embedder=CountingEmbedder())

    assert matrix.shape == (0, 4)


def test_texts_are_sent_in_batches():
    embedder = CountingEmbedder()

    embed_texts(
        a_binding(),
        [f"text {index}" for index in range(10)],
        embedder=embedder,
        batch_size=4,
    )

    assert [len(batch) for batch in embedder.batches] == [4, 4, 2]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_normalising_makes_every_row_a_unit_vector():
    """Cosine similarity becomes a dot product, which is what makes the
    brute-force search in step 5 cheap."""
    matrix = embed_texts(
        a_binding(normalise=True), ["one", "two"], embedder=CountingEmbedder()
    )

    for row in matrix:
        assert float(np.linalg.norm(row)) == pytest.approx(1.0)


def test_not_normalising_leaves_the_backend_output_alone():
    matrix = embed_texts(
        a_binding(normalise=False), ["abcd"], embedder=CountingEmbedder()
    )

    assert float(matrix[0][0]) == 4.0


def test_a_zero_vector_survives_normalisation():
    """A row of zeros has no direction to normalise to, and dividing by its
    norm would produce nan and poison every later comparison silently."""

    class ZeroEmbedder:
        def embed(self, texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), 4), dtype=np.float32)

    matrix = embed_texts(
        a_binding(normalise=True), ["anything"], embedder=ZeroEmbedder()
    )

    assert not np.isnan(matrix).any()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_batches_run_concurrently_up_to_the_stated_limit():
    embedder = CountingEmbedder(delay=0.05)

    embed_texts(
        a_binding(max_async=3),
        [f"text {index}" for index in range(24)],
        embedder=embedder,
        batch_size=2,
    )

    assert 1 < embedder.peak_in_flight <= 3


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def test_progress_is_reported_from_zero_and_never_goes_backwards():
    seen: list[tuple[int, int]] = []
    texts = [f"text {index}" for index in range(10)]

    embed_texts(
        a_binding(),
        texts,
        embedder=CountingEmbedder(),
        batch_size=3,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen[0] == (0, 10)
    assert seen[-1] == (10, 10)
    assert [done for done, _ in seen] == sorted(done for done, _ in seen)


# ---------------------------------------------------------------------------
# A backend that fails
# ---------------------------------------------------------------------------


def test_a_backend_failure_names_the_backend_and_the_model():
    """A stack trace from inside an HTTP client says nothing about which of
    three configured backends was being asked, or for what."""

    class BrokenEmbedder:
        def embed(self, texts: list[str]) -> np.ndarray:
            raise RuntimeError("connection refused")

    with pytest.raises(EmbeddingUnavailable) as raised:
        embed_texts(
            a_binding(kind="ollama", host="http://localhost:11434"),
            ["x"],
            embedder=BrokenEmbedder(),
        )

    message = str(raised.value)
    assert "ollama" in message and "bge-small" in message


# ---------------------------------------------------------------------------
# Naming a backend
# ---------------------------------------------------------------------------


def test_a_local_backend_takes_no_host():
    """fastembed runs an ONNX model in this process. A host means the user
    meant to switch backends and changed the wrong setting."""
    with pytest.raises(SettingsError):
        validate_binding(a_binding(kind="fastembed", host="http://localhost:11434"))


def test_a_daemon_backend_requires_one():
    with pytest.raises(SettingsError):
        validate_binding(a_binding(kind="ollama", host=None))


def test_a_host_that_is_not_a_url_is_refused():
    with pytest.raises(SettingsError) as raised:
        validate_binding(a_binding(kind="ollama", host="ollama"))

    assert "url" in str(raised.value).lower()


def test_the_hosted_backend_may_have_no_host_meaning_the_real_service():
    validate_binding(a_binding(kind="openai", host=None))


def test_an_unknown_backend_is_refused_by_name():
    with pytest.raises(SettingsError) as raised:
        validate_binding(a_binding(kind="mistral"))

    assert "mistral" in str(raised.value)


def test_only_the_daemon_backend_gets_a_default_host():
    """Silently reusing a daemon's address as a hosted base_url would send a
    query somewhere the user never named."""
    assert resolve_host("ollama", None) is not None
    assert resolve_host("openai", None) is None
    assert resolve_host("fastembed", None) is None


def test_an_explicit_host_always_wins():
    assert resolve_host("ollama", "http://elsewhere:1234") == "http://elsewhere:1234"
