"""Fetching a model, and saying so.

Downloading 65 MB is the longest thing a first index does and the one a
reader most needs explained. It used to be reported by huggingface_hub's own
progress bar, drawn with tqdm over the top of kennis's report. Concerns #196,
#209.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from kennis.engine.events import Event, ItemStarted, Recorder
from kennis.engine.rag.embedding import (
    ModelBinding,
    ensure_model_available,
    hf_cache_name,
)


def a_binding(kind: str = "fastembed", model: str = "BAAI/bge-small-en-v1.5"):
    return ModelBinding(kind=kind, model=model, dim=384)


# ---------------------------------------------------------------------------
# Knowing whether a download is coming
# ---------------------------------------------------------------------------


def test_the_cache_directory_is_named_as_huggingface_names_it():
    """`<cache>/models--<org>--<repo>`, which is what the check looks for."""
    assert hf_cache_name("qdrant/bge-small-en-v1.5-onnx-q") == (
        "models--qdrant--bge-small-en-v1.5-onnx-q"
    )


def test_a_model_already_in_the_cache_is_not_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The line has to be true. Announcing a download that does not happen is
    worse than saying nothing, because the next slow start is then not
    believed."""
    from kennis.engine.rag import embedding as module

    monkeypatch.setattr(module, "model_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "_hf_repository", lambda model: "qdrant/whatever")
    (tmp_path / "models--qdrant--whatever").mkdir()
    recorder = Recorder()

    ensure_model_available(a_binding(), events=recorder)

    assert recorder.events_of_type(ItemStarted) == []


def test_a_model_not_in_the_cache_is_announced_before_it_is_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from kennis.engine.rag import embedding as module

    order: list[str] = []
    monkeypatch.setattr(module, "model_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "_hf_repository", lambda model: "qdrant/whatever")
    monkeypatch.setattr(
        module, "_load_fastembed", lambda binding: order.append("fetch")
    )

    class _Watching(Recorder):
        def emit(self, event: Event) -> None:
            if isinstance(event, ItemStarted):
                order.append("announce")
            super().emit(event)

    recorder = _Watching()
    ensure_model_available(a_binding(), events=recorder)

    started = recorder.events_of_type(ItemStarted)
    assert [event.item for event in started] == ["BAAI/bge-small-en-v1.5"]
    assert started[0].operation == "fetch-model"
    # Before, not after: the line exists to explain the pause that follows it.
    assert order == ["announce", "fetch"]


def test_an_unknown_model_is_announced_rather_than_assumed_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A model fastembed does not list has no cache directory to look for.
    Announcing a fetch that turns out to be instant is the safe direction;
    staying silent through a 65 MB download is not."""
    from kennis.engine.rag import embedding as module

    monkeypatch.setattr(module, "model_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "_hf_repository", lambda model: None)
    monkeypatch.setattr(module, "_load_fastembed", lambda binding: None)
    recorder = Recorder()

    ensure_model_available(a_binding(model="who/knows"), events=recorder)

    assert len(recorder.events_of_type(ItemStarted)) == 1


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def _fake_ollama(
    monkeypatch: pytest.MonkeyPatch, held: list[str], pulled: list[str]
) -> None:
    class _Client:
        def __init__(self, host: str | None = None) -> None:
            self.host = host

        def list(self) -> object:
            return types.SimpleNamespace(
                models=[types.SimpleNamespace(model=name) for name in held]
            )

        def pull(self, model: str) -> None:
            pulled.append(model)

    fake = types.ModuleType("ollama")
    monkeypatch.setattr(fake, "Client", _Client, raising=False)
    monkeypatch.setitem(sys.modules, "ollama", fake)


def test_ollama_pulls_a_model_it_does_not_have(monkeypatch: pytest.MonkeyPatch):
    """A person who set `embedding.backend = ollama` and named a model has
    asked for that model. fastembed downloads without being asked; refusing
    for one backend and not the other is an inconsistency a user has to
    learn."""
    pulled: list[str] = []
    _fake_ollama(monkeypatch, held=["llama3:latest"], pulled=pulled)
    recorder = Recorder()

    ensure_model_available(
        ModelBinding(kind="ollama", model="nomic-embed-text", dim=768, host="http://x"),
        events=recorder,
    )

    assert pulled == ["nomic-embed-text"]
    assert [event.item for event in recorder.events_of_type(ItemStarted)] == [
        "nomic-embed-text"
    ]


def test_ollama_does_not_re_pull_a_model_it_already_has(
    monkeypatch: pytest.MonkeyPatch,
):
    """`list()` returns `nomic-embed-text:latest` where the configured name is
    `nomic-embed-text`. An exact match would report every model as missing and
    re-pull it on every index."""
    pulled: list[str] = []
    _fake_ollama(monkeypatch, held=["nomic-embed-text:latest"], pulled=pulled)
    recorder = Recorder()

    ensure_model_available(
        ModelBinding(kind="ollama", model="nomic-embed-text", dim=768, host="http://x"),
        events=recorder,
    )

    assert pulled == []
    assert recorder.events_of_type(ItemStarted) == []


def test_an_explicit_tag_is_matched_exactly(monkeypatch: pytest.MonkeyPatch):
    """`nomic-embed-text:v1.5` must not be satisfied by `:latest`."""
    pulled: list[str] = []
    _fake_ollama(monkeypatch, held=["nomic-embed-text:latest"], pulled=pulled)

    ensure_model_available(
        ModelBinding(
            kind="ollama", model="nomic-embed-text:v1.5", dim=768, host="http://x"
        ),
        events=Recorder(),
    )

    assert pulled == ["nomic-embed-text:v1.5"]


def test_an_unreachable_ollama_does_not_stop_the_attempt(
    monkeypatch: pytest.MonkeyPatch,
):
    """Listing is a convenience, not a gate. If the daemon cannot be asked
    what it holds, the embed call that follows produces the real error - and
    it is a better error than one invented here."""

    class _Client:
        def __init__(self, host: str | None = None) -> None:
            pass

        def list(self) -> object:
            raise ConnectionError("no daemon")

    fake = types.ModuleType("ollama")
    monkeypatch.setattr(fake, "Client", _Client, raising=False)
    monkeypatch.setitem(sys.modules, "ollama", fake)

    ensure_model_available(
        ModelBinding(kind="ollama", model="nomic-embed-text", dim=768, host="http://x"),
        events=Recorder(),
    )


def test_openai_has_nothing_to_fetch(monkeypatch: pytest.MonkeyPatch):
    ensure_model_available(
        ModelBinding(kind="openai", model="text-embedding-3-small", dim=1536),
        events=Recorder(),
    )


# ---------------------------------------------------------------------------
# Where the hook has to be
# ---------------------------------------------------------------------------


def test_building_an_embedder_is_what_fetches_the_model(
    monkeypatch: pytest.MonkeyPatch,
):
    """The hook was first put in `embed_texts`, guarded by "only when no
    embedder was supplied". That covered the search path and missed the
    indexing one - `index` builds an embedder once and hands it to every
    batch, so `embed_texts` always saw one and never fetched. The command
    that actually downloads was the one left unannounced.

    Building an embedder is what needs the model, so that is where it is
    ensured, and this is the test that says so.
    """
    from kennis.engine.rag import embedding as module

    ensured: list[str] = []
    monkeypatch.setattr(
        module,
        "ensure_model_available",
        lambda binding, *, events=None: ensured.append(binding.model),
    )

    module.embedder_for(
        ModelBinding(kind="fastembed", model="BAAI/bge-small-en-v1.5", dim=384)
    )

    assert ensured == ["BAAI/bge-small-en-v1.5"]


def test_an_unusable_binding_is_refused_before_anything_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
):
    """Validation first: a binding kennis will reject must not cost a 65 MB
    download on the way to being rejected."""
    from kennis.engine.errors import SettingsError
    from kennis.engine.rag import embedding as module

    ensured: list[str] = []
    monkeypatch.setattr(
        module,
        "ensure_model_available",
        lambda binding, *, events=None: ensured.append(binding.model),
    )

    with pytest.raises(SettingsError):
        # fastembed runs in this process; a host means the wrong setting was
        # changed, and `validate_binding` refuses it.
        module.embedder_for(
            ModelBinding(kind="fastembed", model="m", dim=8, host="http://x")
        )

    assert ensured == []
