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

import os
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol

import numpy as np
from platformdirs import user_cache_dir

from kennis.engine.errors import EmbeddingUnavailable, SettingsError
from kennis.engine.events import EventSink, ItemStarted
from kennis.engine.settings import credential, load_settings

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

# The operation name a model fetch is reported under. Shared with the front
# ends, which render this one `ItemStarted` where they render no other: a
# fetch is a precondition of the operation rather than one of its items, so
# no later report line accounts for it.
FETCH_MODEL: Final = "fetch-model"

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


def reachable_model(stored: ModelBinding, *, host: str | None) -> ModelBinding:
    """A stored model identity, with the address it can be reached at now.

    **A binding records what the vectors are, not how to reach the thing that
    made them.** `binding.json` holds the backend, the model, the dimension
    and whether vectors were normalised, because those decide whether two
    sets of vectors are comparable. It does not hold the host, and must not:
    two machines reaching the same ollama at different addresses hold the
    same index, and an address written into a shared artefact would make them
    disagree about it.

    The consequence is this function. A query has to be embedded with the
    binding the index was built with, read back from disk - and that binding
    has `host=None`, so an ollama backend is refused by `validate_binding`
    before it can embed anything. Merging the current configuration's host
    into the stored identity is what makes a dense search against an ollama
    index possible at all. Concern #210.

    `host=None` returns the binding unchanged, which is the fastembed case:
    it has no host, and giving it one is refused.
    """
    if host is None:
        return stored
    return replace(stored, host=host)


def embed_texts(
    binding: ModelBinding,
    texts: list[str],
    *,
    embedder: Embedder | None = None,
    batch_size: int = _BATCH_SIZE,
    on_progress: ProgressCallback | None = None,
    events: EventSink | None = None,
) -> np.ndarray:
    """`texts` as an `(len(texts), dim)` float32 matrix, in input order.

    `embedder` is supplied by the caller so a test hands over something that
    never downloads a model; left out, one is built for `binding.kind`, and
    building it fetches the model. A test that drives the command line
    supplies nothing, so it does acquire a network dependency - what keeps
    the suite offline is `KENNIS_EMBEDDING_BACKEND=none`, set for every test
    by `tests/conftest.py`. Concern #253.

    `on_progress(done, total)` is called with zero up front and after each
    batch, and `done` never decreases - batches finish out of order, so the
    count is accumulated under a lock rather than inferred from which batch
    returned.
    """
    if not texts:
        # Shaped rather than empty, so a caller can stack this without a
        # special case for the collection that had nothing in it.
        return np.zeros((0, binding.dim), dtype=np.float32)

    active = embedder if embedder is not None else embedder_for(binding, events=events)
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


def embedder_for(binding: ModelBinding, *, events: EventSink | None = None) -> Embedder:
    """The backend `binding` names.

    Imported at call time rather than at module import, so that installing
    kennis without a backend's optional dependency costs nothing until it is
    actually selected.

    **Building an embedder is what needs the model**, so the fetch is
    ensured here rather than at each call site. `index` builds one and
    hands it to every batch; `search` lets `embed_texts` build one for a
    single query. Hooking only the second left the first - the one that
    actually downloads - unannounced. After validation, so an unusable
    binding is refused rather than fetched for.
    """
    validate_binding(binding)
    ensure_model_available(binding, events=events)
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


def model_cache_dir() -> Path:
    """Where a downloaded embedding model is kept.

    Chosen rather than inherited. fastembed defaults to
    `<tempdir>/fastembed_cache`, which on Linux is emptied by a reboot or by
    a tmpfiles sweep - so a 65 MB download is paid again at unpredictable
    intervals, and when the directory has gone mid-life the failure surfaces
    as an ONNX runtime `NO_SUCHFILE` naming a path the user has never seen.
    A cache directory is the right place for a file that is expensive to
    fetch and cheap to lose. Concern #196.
    """
    return Path(user_cache_dir("kennis")) / "models"


# huggingface_hub reads this **at import time** into a module constant, so it
# has to be set before anything imports it - which here means before fastembed
# is imported, since that is what pulls it in.
_HF_QUIET: Final = "HF_HUB_DISABLE_PROGRESS_BARS"


def _quieten_downloads() -> None:
    """Stop huggingface_hub drawing its own progress bar.

    It writes `Fetching 5 files: 100%|...` to stderr with tqdm, in the middle
    of kennis's report and knowing nothing of its layout. Nothing is lost by
    turning it off: the fetch is announced as an event, and events reach the
    log whether or not a front end shows them.

    Through the environment rather than `huggingface_hub.utils.
    disable_progress_bars`, which is not an exported name - importing it
    would need a silenced type error, and the variable is the interface the
    library documents.

    `setdefault`, so somebody who has deliberately set it to `0` keeps their
    bars.
    """
    os.environ.setdefault(_HF_QUIET, "1")


def hf_cache_name(repository: str) -> str:
    """The directory huggingface caches `repository` under.

    `org/repo` becomes `models--org--repo`. Spelled out here rather than
    imported so the check does not depend on a private helper of
    `huggingface_hub`, and tested against a real repository name.
    """
    return f"models--{repository.replace('/', '--')}"


def _hf_repository(model: str) -> str | None:
    """The huggingface repository fastembed downloads `model` from.

    Read from the *installed* fastembed rather than hardcoded, because the
    spelling is version-dependent: 0.8.0 lists `qdrant/...-onnx-q` and 0.8.1
    lists `Qdrant/...-onnx-Q`, which are different cache directories for the
    same weights. Concern #209.

    None for a model fastembed does not list, which is a model kennis cannot
    say anything about in advance.
    """
    from fastembed import TextEmbedding

    for entry in TextEmbedding.list_supported_models():
        if entry.get("model") == model:
            sources = entry.get("sources") or {}
            found = sources.get("hf")
            return str(found) if found else None
    return None


def _load_fastembed(binding: ModelBinding) -> None:
    """Construct the model, which downloads it if it is not cached."""
    _FastembedEmbedder(binding).warm()


def ensure_model_available(
    binding: ModelBinding, *, events: EventSink | None = None
) -> None:
    """Fetch the model this binding names, saying so first if it is not here.

    Called by `embed_texts` only when it built the embedder itself. A caller
    that supplies its own never reaches it; a caller that does not - which
    includes every test driving the command line - reaches it and downloads.
    The suite stays offline by configuring the backend away, not by this
    path being unreachable from a test. Concern #253.

    **The announcement comes before the fetch**, because it exists to explain
    the pause that follows it. Where kennis cannot tell whether a fetch is
    needed it announces one: a line that turns out to describe an instant
    operation is a smaller fault than sixty seconds of silence.
    """
    if binding.kind == "fastembed":
        # First, and before anything imports fastembed - which is what pulls
        # huggingface_hub in, and huggingface_hub reads the variable at
        # import. `_hf_repository` below imports fastembed to read the model
        # list, so doing this any later is too late.
        _quieten_downloads()
        _ensure_fastembed(binding, events)
    elif binding.kind == "ollama":
        _ensure_ollama(binding, events)
    # openai holds its models on its own servers; there is nothing to fetch.


def _ensure_fastembed(binding: ModelBinding, events: EventSink | None) -> None:
    repository = _hf_repository(binding.model)
    cached = (
        repository is not None
        and (model_cache_dir() / hf_cache_name(repository)).is_dir()
    )
    if cached:
        return
    _announce(binding.model, events)
    _load_fastembed(binding)


def _ensure_ollama(binding: ModelBinding, events: EventSink | None) -> None:
    """Pull the model if the daemon does not hold it.

    fastembed downloads without being asked, and somebody who set
    `embedding.backend = ollama` and named a model has asked for that model;
    refusing for one backend and not for the other is an inconsistency a user
    would have to learn. A name ollama does not recognise is answered with a
    404, so a typo is an error rather than a large download.
    """
    from ollama import Client

    client = Client(host=binding.host)
    try:
        held = {str(entry.model) for entry in client.list().models if entry.model}
    except Exception:
        # Listing is a convenience, not a gate. If the daemon cannot be asked
        # what it holds, the embed call that follows produces the real error,
        # and it is a better error than one invented here.
        return
    if _ollama_holds(binding.model, held):
        return
    _announce(binding.model, events)
    client.pull(binding.model)


def _ollama_holds(wanted: str, held: set[str]) -> bool:
    """Whether `held` satisfies `wanted`, allowing for the implicit tag.

    `list()` returns `nomic-embed-text:latest` where a configured model is
    usually written `nomic-embed-text`. Matching exactly would report every
    model as missing and re-pull it on every index. An explicitly tagged name
    is matched exactly, because `:v1.5` is a request for that version.
    """
    if wanted in held:
        return True
    return ":" not in wanted and f"{wanted}:latest" in held


def _announce(model: str, events: EventSink | None) -> None:
    if events is not None:
        events.emit(ItemStarted(operation=FETCH_MODEL, item=model))


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

    def warm(self) -> None:
        """Load the model, downloading it if it is not cached.

        Separate from `embed` so the fetch can be announced before it starts
        rather than discovered by a reader watching nothing happen.
        """
        self._model()

    def _model(self) -> TextEmbedding:
        """The loaded model, shared across batches.

        Typed as `TextEmbedding` rather than as `Embedder`: its `embed`
        yields an iterable of vectors rather than a matrix, so it does not
        satisfy the protocol, and `embed` above is what makes it a matrix.
        """
        # Before the import, not after it: see `_quieten_downloads`.
        _quieten_downloads()
        from fastembed import TextEmbedding

        with self._loading:
            if self._binding.model not in self._loaded:
                # fastembed calls `enable_progress_bars()` in a `finally`
                # after each download, and huggingface_hub answers that with
                # a UserWarning when the environment variable has already
                # turned them off. The variable wins - the bar does not
                # appear - so the warning reports a conflict kennis created
                # deliberately and tells the reader nothing they can act on.
                # Caught rather than left to print, because `filterwarnings =
                # ["error"]` would otherwise make it fatal in a test that
                # ever loads a real model.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message=".*progress bars.*", category=UserWarning
                    )
                    self._loaded[self._binding.model] = TextEmbedding(
                        model_name=self._binding.model,
                        cache_dir=str(model_cache_dir()),
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
        # server, which usually accepts any key at all.
        #
        # The key is read through `credential`, so a key typed into
        # `config init` works. The environment still wins, and passing an
        # empty one through would override the library's own lookup with
        # nothing, so it is passed only when there is one. Concern #131.
        key = credential(load_settings().embedding.api_key_env)
        client = (
            OpenAI(base_url=self._binding.host, api_key=key)
            if key
            else OpenAI(base_url=self._binding.host)
        )
        response = client.embeddings.create(model=self._binding.model, input=texts)
        return np.array([item.embedding for item in response.data], dtype=np.float32)
