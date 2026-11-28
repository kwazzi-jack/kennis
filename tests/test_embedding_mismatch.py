"""A backend and a model that may not belong together, said when they fail.

Brian, 2026-11-25: the configuration is literal - ollama with
`BAAI/bge-small-en-v1.5` is allowed, and defaults never follow another
setting - and the operation that uses them is what says there may be a
mismatch, with what kennis can tell about the value. Measured before this:
fastembed with `nomic-embed-text` announced a download and then failed with
fastembed's own `ValueError`, naming no setting.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from kennis.engine.errors import EmbeddingUnavailable
from kennis.engine.events import Event
from kennis.engine.rag.embedding import ModelBinding, embed_texts, embedder_for

OLLAMA_AT = "http://localhost:11434"


class Recorded:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class Refusing:
    """An embedder whose service answers every batch with an error."""

    def embed(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("Error code: 404 - model_not_found")


@pytest.fixture
def ollama_lacking_everything(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """An ollama daemon that holds no model and cannot pull the one asked
    for; the list records what was pulled."""
    pulled: list[str] = []

    class Client:
        def __init__(self, host: str | None = None) -> None:
            self.host = host

        def list(self) -> SimpleNamespace:
            return SimpleNamespace(models=[])

        def pull(self, model: str) -> None:
            pulled.append(model)
            raise RuntimeError("pull model manifest: file does not exist")

    import ollama

    monkeypatch.setattr(ollama, "Client", Client)
    return pulled


def test_fastembed_with_an_ollama_model_names_both_settings_and_downloads_nothing():
    recorded = Recorded()

    with pytest.raises(EmbeddingUnavailable) as raised:
        embedder_for(
            ModelBinding(kind="fastembed", model="nomic-embed-text"), events=recorded
        )

    said = str(raised.value)
    assert "embedding.backend" in said and "embedding.model" in said
    assert "nomic-embed-text" in said
    # What kennis can tell: it is ollama's usual model, and fastembed has none
    # by that name.
    assert "ollama" in said
    assert recorded.events == [], "nothing is downloaded for a name fastembed lacks"


def test_ollama_with_a_fastembed_model_is_tried_and_said_to_be_fastembed_s(
    ollama_lacking_everything: list[str],
):
    """Allowed and tried: kennis asks ollama for it, and when ollama cannot,
    says the name is fastembed's."""
    with pytest.raises(EmbeddingUnavailable) as raised:
        embedder_for(
            ModelBinding(kind="ollama", model="BAAI/bge-small-en-v1.5", host=OLLAMA_AT)
        )

    assert ollama_lacking_everything == ["BAAI/bge-small-en-v1.5"]
    said = str(raised.value)
    assert "fastembed" in said
    assert "embedding.model" in said and "embedding.backend" in said
    assert OLLAMA_AT in said
    assert raised.value.resolution == "ollama list"


def test_ollama_with_a_name_kennis_knows_nothing_about_still_names_the_settings(
    ollama_lacking_everything: list[str],
):
    with pytest.raises(EmbeddingUnavailable) as raised:
        embedder_for(ModelBinding(kind="ollama", model="llama-embed", host=OLLAMA_AT))

    said = str(raised.value)
    assert "llama-embed" in said and OLLAMA_AT in said
    assert "embedding.model" in said
    assert "fastembed" not in said, "no insight claimed where kennis has none"


def test_openai_with_a_fastembed_model_says_so_when_the_service_refuses():
    binding = ModelBinding(kind="openai", model="BAAI/bge-small-en-v1.5")

    with pytest.raises(EmbeddingUnavailable) as raised:
        embed_texts(binding, ["a passage"], embedder=Refusing())

    said = str(raised.value)
    assert "model_not_found" in said, "the service's own answer is kept"
    assert "fastembed" in said and "embedding.model" in said
