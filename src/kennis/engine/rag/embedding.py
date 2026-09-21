"""Embedding backends: a local ONNX model by default, or Ollama or OpenAI.

A `ModelBinding` names a model and where to reach it; `embed_texts` turns a
list of strings into an `(n, dim)` float32 matrix. Both lifecycles use this -
a build embeds every chunk once, a query embeds one question.

`fastembed` is the default because it runs a small ONNX model in this process
with no server, no API key and no network beyond a one-time model download,
so indexing and searching work with nothing else installed or running.
`ollama` and `openai` are for anyone who already has that infrastructure, and
`host` doubles as an OpenAI `base_url` override so a local vLLM or TGI is
reachable through the same path.

Two departures from boepie, which this is otherwise a port of.

**The interface is synchronous.** Design section 20 says the engine is, and
that only fetchers hide concurrency inside. boepie is `async` to the top.

**Concurrency is a bounded thread pool, not an event loop.** boepie gathers
coroutines behind a semaphore and then pushes fastembed *back* onto a thread,
because ONNX inference is CPU-bound and blocking. Threads with the
synchronous clients give the same bounded concurrency for the network
backends, need no event loop for the local one, and leave this module
callable from anywhere. Row order is restored by index rather than by
completion order, so a vector stays attached to its text.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol

import numpy as np

from kennis.engine.errors import EmbeddingUnavailable, SettingsError

if TYPE_CHECKING:
    # Imported for the type only. The runtime import stays inside the
    # method, so installing kennis without a backend's dependency costs
    # nothing until that backend is selected.
    from fastembed import TextEmbedding

type Kind = Literal["fastembed", "ollama", "openai"]

# `(done, total)`, called with zero up front and after each batch.
type ProgressCallback = Callable[[int, int], None]

KINDS: Final[tuple[str, ...]] = ("fastembed", "ollama", "openai")

# Texts per request. Both hosted backends accept a batch; a modest size bounds
# the peak request while still amortising per-call overhead.
_BATCH_SIZE: Final = 64

# In-flight batches when a binding does not set its own.
_MAX_IN_FLIGHT: Final = 4

# The daemon's usual address, used only when the daemon backend is selected.
_OLLAMA_DEFAULT_HOST: Final = "http://localhost:11434"


class Embedder(Protocol):
    """Whatever turns a batch of texts into a matrix of vectors.

    A protocol rather than a class hierarchy because the three backends have
    nothing in common but this call, and because it is the seam a test needs:
    no test in this project downloads a model.
    """

    def embed(self, texts: list[str]) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """An embedding model, and where to reach it.

    `host` is the daemon address for ollama, and for openai a `base_url`
    override where None means the real service. fastembed ignores it, and is
    refused if one is given, because a host there means the user meant to
    switch backends and changed the wrong setting.

    `normalise` scales every vector to unit length, which makes cosine
    similarity a plain dot product. It is recorded in the derivation binding,
    so turning it off is a complete cache miss - normalised and unnormalised
    vectors are not comparable, and the difference is invisible in the
    numbers themselves.
    """

    kind: str
    model: str
    dim: int
    host: str | None = None
    normalise: bool = True
    max_async: int | None = None


def embed_texts(
    binding: ModelBinding,
    texts: list[str],
    *,
    embedder: Embedder | None = None,
    batch_size: int = _BATCH_SIZE,
    on_progress: ProgressCallback | None = None,
) -> np.ndarray:
    """`texts` as an `(len(texts), dim)` float32 matrix, in input order.

    `embedder` is supplied by the caller so a test hands over something that
    never downloads a model; left out, one is built for `binding.kind`.

    `on_progress(done, total)` is called with zero up front and after each
    batch, and `done` never decreases - batches finish out of order, so the
    count is accumulated under a lock rather than inferred from which batch
    returned.
    """
    if not texts:
        # Shaped rather than empty, so a caller can stack this without a
        # special case for the collection that had nothing in it.
        return np.zeros((0, binding.dim), dtype=np.float32)

    active = embedder if embedder is not None else embedder_for(binding)
    batches = [texts[at : at + batch_size] for at in range(0, len(texts), batch_size)]
    results: list[np.ndarray | None] = [None] * len(batches)

    counted = threading.Lock()
    done = 0
    if on_progress is not None:
        on_progress(0, len(texts))

    def run(position: int, batch: list[str]) -> None:
        nonlocal done
        results[position] = _embedded(active, binding, batch)
        if on_progress is not None:
            with counted:
                done += len(batch)
                on_progress(done, len(texts))

    in_flight = binding.max_async or _MAX_IN_FLIGHT
    with ThreadPoolExecutor(max_workers=in_flight) as pool:
        for outcome in [
            pool.submit(run, position, batch) for position, batch in enumerate(batches)
        ]:
            outcome.result()

    matrix = np.vstack([result for result in results if result is not None])
    return _normalised(matrix) if binding.normalise else matrix


def embedder_for(binding: ModelBinding) -> Embedder:
    """The backend `binding` names.

    Imported at call time rather than at module import, so that installing
    kennis without a backend's optional dependency costs nothing until it is
    actually selected.
    """
    validate_binding(binding)
    if binding.kind == "fastembed":
        return _FastembedEmbedder(binding)
    if binding.kind == "ollama":
        return _OllamaEmbedder(binding)
    return _OpenAiEmbedder(binding)


def resolve_host(kind: str, host: str | None) -> str | None:
    """The effective host: an explicit value wins, otherwise the default.

    Only the daemon backend has a default. fastembed has no server, and
    silently reusing the daemon's address as a hosted `base_url` would send a
    query somewhere the user never named.
    """
    if host is not None:
        return host
    return _OLLAMA_DEFAULT_HOST if kind == "ollama" else None


def validate_binding(binding: ModelBinding) -> None:
    """Refuse a binding that cannot work, before any call is made.

    Catching this here beats discovering it after a backend has been asked
    for the first batch of a corpus.
    """
    if binding.kind not in KINDS:
        raise SettingsError(
            f"'{binding.kind}' is not an embedding backend kennis knows: "
            f"choose one of {', '.join(KINDS)}"
        )
    if binding.kind == "fastembed":
        if binding.host is not None:
            raise SettingsError(
                "the fastembed backend runs a model in this process and takes no "
                "host; omit it, or choose a backend that has a server"
            )
        return
    if binding.host is None:
        if binding.kind == "ollama":
            raise SettingsError("the ollama backend needs the address of its daemon")
        return
    if not binding.host.startswith(("http://", "https://")):
        raise SettingsError(
            f"'{binding.host}' is not a URL: the {binding.kind} backend needs an "
            "address like http://localhost:11434"
        )


def _embedded(
    embedder: Embedder, binding: ModelBinding, batch: list[str]
) -> np.ndarray:
    """One batch, with a failure that says which backend was being asked.

    A refused connection from inside an HTTP client names a port and nothing
    else - not which of three configured backends it was, nor which model.
    """
    try:
        return np.asarray(embedder.embed(batch), dtype=np.float32)
    except Exception as error:
        where = f" at {binding.host}" if binding.host else ""
        raise EmbeddingUnavailable(
            f"the {binding.kind} backend could not embed with "
            f"'{binding.model}'{where}: {error}"
        ) from error


def _normalised(matrix: np.ndarray) -> np.ndarray:
    """Every row scaled to unit length, leaving zero rows alone.

    A row of zeros has no direction to normalise to, and dividing by its norm
    would put `nan` into the matrix - which does not raise, compares false
    against everything, and would quietly remove that chunk from every
    result.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class _FastembedEmbedder:
    """A small ONNX model, loaded once per process and reused.

    The model is held on the class because loading it is the expensive part -
    a cold process reaches model-ready in about 0.4 seconds, and the first
    ever use on a machine downloads it - so concurrent batches for the same
    model must share one rather than each initialising its own.
    """

    # Shared across every instance on purpose: loading is the expensive part,
    # so two concurrent batches for one model must not each initialise it.
    # A `ClassVar` because it is exactly that - state of the class, not of an
    # instance - which is also what stops ruff reading it as a mutable
    # default.
    _loaded: ClassVar[dict[str, TextEmbedding]] = {}
    _loading: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, binding: ModelBinding) -> None:
        self._binding = binding

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self._model().embed(texts)), dtype=np.float32)

    def _model(self) -> TextEmbedding:
        """The loaded model, shared across batches.

        Typed as `TextEmbedding` rather than as `Embedder`: its `embed`
        yields an iterable of vectors rather than a matrix, so it does not
        satisfy the protocol, and `embed` above is what makes it a matrix.
        """
        from fastembed import TextEmbedding

        with self._loading:
            if self._binding.model not in self._loaded:
                self._loaded[self._binding.model] = TextEmbedding(
                    model_name=self._binding.model
                )
        return self._loaded[self._binding.model]


class _OllamaEmbedder:
    def __init__(self, binding: ModelBinding) -> None:
        self._binding = binding

    def embed(self, texts: list[str]) -> np.ndarray:
        from ollama import Client

        response = Client(host=self._binding.host).embed(
            model=self._binding.model, input=texts
        )
        return np.array(response.embeddings, dtype=np.float32)


class _OpenAiEmbedder:
    def __init__(self, binding: ModelBinding) -> None:
        self._binding = binding

    def embed(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        # base_url=None is the real service; a URL is any OpenAI-compatible
        # server. The key comes from OPENAI_API_KEY, which local servers
        # usually accept any value for.
        client = OpenAI(base_url=self._binding.host)
        response = client.embeddings.create(model=self._binding.model, input=texts)
        return np.array([item.embedding for item in response.data], dtype=np.float32)
