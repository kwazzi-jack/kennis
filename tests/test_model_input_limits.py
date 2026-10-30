"""How much an embedding model reads, checked at index time and said when
the settings change (#577).

OpenAI refused a batch because one passage was over 8,192 tokens, and the
default local model reads 512 and drops the rest without a word. The ceiling
(#578) bounds a chunk's characters; this says, per model, whether that is
enough, and makes sure no request is refused for length.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.corpus.add import add_notes
from kennis.engine.corpus.collection import Collection
from kennis.engine.errors import EmbeddingUnavailable
from kennis.engine.events import Diagnostic, PassagesCutShort, Recorder, Severity
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import MeasuresInput, ModelBinding, _FastembedEmbedder
from kennis.engine.rag.index import build_index
from kennis.engine.rag.limits import (
    DENSEST_CHARACTERS_PER_TOKEN,
    PROSE_CHARACTERS_PER_TOKEN,
    ChunkFit,
    chunk_fit,
    input_tokens,
    shortened_to_bytes,
)
from kennis.engine.rag.loaders import CollectionLoader
from kennis.render.diagnostics import describe_diagnostic
from kennis.render.settings import describe_fit
from test_gui_kennis_settings import (  # noqa: F401 - `client` is a fixture
    HTMX,
    client,
    form_of,
    row_of,
    section_of,
    sent_from,
)

# ---------------------------------------------------------------------------
# What a model reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("backend", "model", "tokens"),
    [
        ("openai", "text-embedding-3-small", 8192),
        ("openai", "text-embedding-3-large", 8192),
        ("openai", "text-embedding-ada-002", 8191),
        ("fastembed", "BAAI/bge-small-en-v1.5", 512),
    ],
)
def test_a_published_limit_is_known(backend: str, model: str, tokens: int):
    assert input_tokens(backend, model) == tokens


@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("ollama", "nomic-embed-text"),
        ("openai", "a-model-on-a-compatible-server"),
        ("fastembed", "BAAI/bge-small-en-v1.5-but-another"),
    ],
)
def test_anything_else_is_unknown_and_never_assumed_to_fit(backend: str, model: str):
    assert input_tokens(backend, model) is None


# ---------------------------------------------------------------------------
# Whether a chunk fits
# ---------------------------------------------------------------------------


def test_the_estimates_are_the_measured_ratios():
    fit = chunk_fit(1500, "openai", "text-embedding-3-large")

    assert fit == ChunkFit(
        ceiling=3000,
        prose_tokens=round(1500 / PROSE_CHARACTERS_PER_TOKEN),
        densest_tokens=round(3000 / DENSEST_CHARACTERS_PER_TOKEN),
        model_tokens=8192,
        verdict="fits",
    )


@pytest.mark.parametrize(
    ("size", "backend", "model", "verdict"),
    [
        (1500, "openai", "text-embedding-3-large", "fits"),
        (1500, "fastembed", "BAAI/bge-small-en-v1.5", "dense-may-not-fit"),
        (3000, "fastembed", "BAAI/bge-small-en-v1.5", "may-not-fit"),
        (1500, "ollama", "nomic-embed-text", "unknown"),
    ],
)
def test_the_verdict(size: int, backend: str, model: str, verdict: str):
    assert chunk_fit(size, backend, model).verdict == verdict


def test_with_no_model_there_is_nothing_to_fit():
    assert chunk_fit(1500, "none", "") is None


@pytest.mark.parametrize(
    ("fit", "said"),
    [
        (chunk_fit(1500, "openai", "text-embedding-3-large"), "every chunk fits"),
        (
            chunk_fit(1500, "fastembed", "BAAI/bge-small-en-v1.5"),
            "a dense table or equation near that length does not",
        ),
        (
            chunk_fit(3000, "fastembed", "BAAI/bge-small-en-v1.5"),
            "even a chunk of prose is longer than that",
        ),
        (chunk_fit(1500, "ollama", "nomic-embed-text"), "kennis does not know"),
    ],
)
def test_each_verdict_is_said_with_its_numbers(fit: ChunkFit | None, said: str):
    assert fit is not None
    words = describe_fit(fit, model="the model")

    assert said in words
    assert str(fit.ceiling) in words
    if fit.model_tokens is not None:
        assert str(fit.model_tokens) in words


# ---------------------------------------------------------------------------
# Shortening for a byte-level tokenizer
# ---------------------------------------------------------------------------


def test_a_text_within_the_limit_is_sent_as_it_is():
    texts, shortened = shortened_to_bytes(["short", "x" * 8192], 8192)

    assert texts == ["short", "x" * 8192]
    assert shortened == 0


# One, two, three and four bytes in UTF-8.
@pytest.mark.parametrize("character", ["x", chr(0xE9), chr(0x8A9E), chr(0x1F600)])
def test_a_longer_text_is_cut_at_a_character_within_the_limit(character: str):
    text = character * 9000

    [sent], shortened = shortened_to_bytes([text], 8192)

    assert shortened == 1
    assert len(sent.encode("utf-8")) <= 8192
    assert text.startswith(sent)
    assert len(sent.encode("utf-8")) > 8192 - 4


# ---------------------------------------------------------------------------
# At index time
# ---------------------------------------------------------------------------


class Recording:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.sent.extend(texts)
        return np.ones((len(texts), 4), dtype=np.float32)


class Measuring(Recording):
    """A model that reads `limit` characters, standing in for a tokenizer."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def input_limit(self) -> int:
        return self.limit

    def overflowing(self, texts: list[str]) -> int:
        return sum(len(text) > self.limit for text in texts)


def a_corpus(tmp_path: Path, notes: dict[str, str]) -> Collection:
    collection = Collection(root=tmp_path / "corpus", name="notes")
    for name, body in notes.items():
        source = tmp_path / "sources" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(body, encoding="utf-8")
        add_notes(collection, [str(source)])
    return collection


def built(
    tmp_path: Path, collection: Collection, model: ModelBinding, embedder: Recording
) -> list[Diagnostic]:
    recorder = Recorder()
    build_index(
        CollectionLoader(collection),
        index_root=tmp_path / "index",
        binding=Binding(chunking=ChunkParameters(), model=model),
        embedder=embedder,
        events=recorder,
    )
    return [event for event in recorder.events if isinstance(event, Diagnostic)]


# A fenced block of 2,800 three-byte characters: whole under the ceiling of
# 3,000 characters, and 8,400 bytes, so not provably within 8,192 tokens.
WIDE = "```\n" + chr(0x8A9E) * 2800 + "\n```\n"


def test_openai_is_never_sent_more_bytes_than_it_reads_tokens(tmp_path: Path):
    collection = a_corpus(tmp_path, {"wide.md": WIDE, "plain.md": "# Plain\n\nText.\n"})
    embedder = Recording()
    model = ModelBinding(kind="openai", model="text-embedding-3-large")

    diagnostics = built(tmp_path, collection, model, embedder)

    assert max(len(text.encode("utf-8")) for text in embedder.sent) <= 8192
    [cut] = [
        one.detail for one in diagnostics if isinstance(one.detail, PassagesCutShort)
    ]
    assert cut == PassagesCutShort(
        model="text-embedding-3-large",
        limit=8192,
        count=1,
        total=len(embedder.sent),
        shortened=True,
    )


def test_a_model_that_truncates_is_counted_and_sent_everything(tmp_path: Path):
    long = "# Long\n\n" + "word " * 500 + "\n"
    collection = a_corpus(tmp_path, {"long.md": long, "short.md": "# Short\n\nText.\n"})
    embedder = Measuring(limit=300)
    model = ModelBinding(kind="fastembed", model="BAAI/bge-small-en-v1.5")

    diagnostics = built(tmp_path, collection, model, embedder)

    [cut] = [one for one in diagnostics if isinstance(one.detail, PassagesCutShort)]
    assert cut.severity is Severity.WARNING
    assert isinstance(cut.detail, PassagesCutShort)
    assert cut.detail.limit == 300
    assert cut.detail.count == sum(len(text) > 300 for text in embedder.sent)
    assert cut.detail.count > 0
    assert cut.detail.shortened is False
    assert any(len(text) > 300 for text in embedder.sent)


def test_nothing_is_said_when_every_passage_fits(tmp_path: Path):
    collection = a_corpus(tmp_path, {"short.md": "# Short\n\nText.\n"})

    diagnostics = built(
        tmp_path,
        collection,
        ModelBinding(kind="fastembed", model="BAAI/bge-small-en-v1.5"),
        Measuring(limit=10_000),
    )

    assert not [one for one in diagnostics if isinstance(one.detail, PassagesCutShort)]


def test_the_warning_says_who_reads_what():
    detail = PassagesCutShort(
        model="BAAI/bge-small-en-v1.5",
        limit=512,
        count=904,
        total=11748,
        shortened=False,
    )

    said = describe_diagnostic(detail)

    assert "904 of 11748" in said
    assert "BAAI/bge-small-en-v1.5" in said
    assert "512 tokens" in said
    assert "keyword search reads all of it" in said
    assert "kennis shortened" in describe_diagnostic(
        PassagesCutShort(model="m", limit=8192, count=1, total=2, shortened=True)
    )


# ---------------------------------------------------------------------------
# Said when the settings change
# ---------------------------------------------------------------------------


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    return CliRunner()


def test_config_set_says_whether_a_chunk_fits(configured: CliRunner):
    result = configured.invoke(main, ["config", "set", "chunking.size", "3000"])

    assert result.exit_code == 0, result.output
    assert "warning:" in result.output
    assert "512" in result.output
    assert "even a chunk of prose is longer than that" in result.output


def test_config_set_of_the_model_says_it_too(configured: CliRunner):
    configured.invoke(main, ["config", "set", "embedding.backend", "openai"])
    result = configured.invoke(
        main, ["config", "set", "embedding.model", "text-embedding-3-large"]
    )

    assert result.exit_code == 0, result.output
    assert "every chunk fits" in result.output
    assert "warning:" not in result.output


def test_another_setting_says_nothing_about_fit(configured: CliRunner):
    result = configured.invoke(main, ["config", "set", "retrieval.default_top_k", "4"])

    assert "fits" not in result.output and "tokens" not in result.output


def test_the_settings_page_says_it_on_the_chunk_size_row(client: TestClient):  # noqa: F811
    section = section_of(client.get("/settings/kennis", headers=HTMX).text)

    fit = row_of(section, "chunking.size").find(class_="fit")

    assert fit is not None
    assert "512" in fit.get_text()


def test_changing_the_size_redraws_with_the_new_fit(client: TestClient):  # noqa: F811
    """Sent as the page sends it: the size field asks for the redraw and
    includes every `[data-redraw]` field of the form."""
    form = form_of(section_of(client.get("/settings/kennis", headers=HTMX).text))
    size = form.find("input", attrs={"name": "chunking.size"})
    assert size is not None
    assert size["hx-get"] == "/settings/kennis"
    assert size["hx-include"] == ".kennis-settings [data-redraw]"
    sent = {
        name: value
        for name, value in sent_from(form, **{"chunking.size": "3000"}).items()
        if (control := form.find(attrs={"name": name})) is not None
        and control.has_attr("data-redraw")
    }

    redrawn = section_of(
        client.get(str(size["hx-get"]), params=sent, headers=HTMX).text
    )

    fit = row_of(redrawn, "chunking.size").find(class_="fit")
    assert fit is not None
    assert "even a chunk of prose is longer than that" in fit.get_text()


# ---------------------------------------------------------------------------
# fastembed's own measure, against a tokenizer that stands in for the model's
# ---------------------------------------------------------------------------


class Encoded:
    def __init__(self, overflowing: list[object]) -> None:
        self.overflowing = overflowing


class StandInTokenizer:
    """Cuts at `limit` words, as `tokenizers` does at `max_length` ids."""

    def __init__(self, truncation: dict[str, object] | None) -> None:
        self.truncation = truncation

    def encode_batch(self, texts: list[str]) -> list[Encoded]:
        limit = int(str((self.truncation or {}).get("max_length", 0)))
        return [
            Encoded(["rest"] if len(text.split()) > limit else []) for text in texts
        ]


def a_fastembed(
    monkeypatch: pytest.MonkeyPatch, truncation: dict[str, object] | None
) -> _FastembedEmbedder:
    embedder = _FastembedEmbedder(
        ModelBinding(kind="fastembed", model="BAAI/bge-small-en-v1.5")
    )
    monkeypatch.setattr(embedder, "_tokenizer", lambda: StandInTokenizer(truncation))
    return embedder


def test_fastembed_counts_only_the_texts_its_tokenizer_cuts(
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = a_fastembed(monkeypatch, {"max_length": 3})

    assert isinstance(embedder, MeasuresInput)
    assert embedder.input_limit() == 3
    assert embedder.overflowing(["one two", "one two three four", "a b c d e"]) == 2


@pytest.mark.parametrize("truncation", [None, {}, {"max_length": "512"}])
def test_a_tokenizer_that_states_no_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch, truncation: dict[str, object] | None
):
    with pytest.raises(EmbeddingUnavailable, match="states no input limit"):
        a_fastembed(monkeypatch, truncation).input_limit()
