"""An index is searched with the model it was built with (GitHub issue #16).

Brian switched the embedding backend from fastembed to ollama, set ollama's
address and reindexed the corpus; a search inside a project then failed
whole, because the project's own index was still fastembed's and the search
attached ollama's address to it, which `validate_binding` refuses. Brian's
answers (2026-11-09): the configured address belongs to the configured
backend only; an index built with another model is searched with it and
named, with the command that rebuilds it; and a scope whose model cannot
embed the question is matched by keywords and named, rather than failing
every other scope.

The embedding model is a stand-in, but `validate_binding` is not: it is
what refused.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.rag import embedding as embedding_module
from kennis.engine.rag.embedding import ModelBinding, address_for, resolve_host
from kennis.engine.settings import EmbeddingSettings, LoggingSettings
from kennis.retrieval import OtherModel, Unembedded, sweep

OLLAMA_ADDRESS = "http://localhost:11434"


class StandIn:
    """Vectors from a hash of each text: the same text, the same vector."""

    def __init__(self, binding: ModelBinding) -> None:
        self.binding = binding

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = [
            [
                byte / 255
                for byte in hashlib.blake2b(text.encode(), digest_size=8).digest()
            ]
            for text in texts
        ]
        return np.asarray(rows, dtype=np.float32)


class Unreachable(StandIn):
    def embed(self, texts: list[str]) -> np.ndarray:
        raise ConnectionError("connection refused")


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embedding_module, "ensure_model_available", lambda *_, **__: None
    )
    monkeypatch.setattr(embedding_module, "_FastembedEmbedder", StandIn)
    monkeypatch.setattr(embedding_module, "_OllamaEmbedder", StandIn)


@pytest.fixture
def built_with_fastembed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stand_in: None
) -> Path:
    """A corpus whose notes are indexed with fastembed, then the
    configuration changed to ollama with its address, as Brian did."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "fastembed")
    monkeypatch.setenv("KENNIS_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for name, body in [
        ("calibration", "Gains are solved per antenna and per interval."),
        ("imaging", "The dirty image is deconvolved with CLEAN."),
    ]:
        source = tmp_path / "sources" / f"{name}.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
        added = run.invoke(main, ["corpus", "add", "-n", str(source)])
        assert added.exit_code == 0, added.output
    indexed = run.invoke(main, ["corpus", "index", "--collection", "notes"])
    assert indexed.exit_code == 0, indexed.output
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("KENNIS_EMBEDDING_MODEL", "embeddinggemma-2:570m")
    monkeypatch.setenv("KENNIS_EMBEDDING_BASE_URL", OLLAMA_ADDRESS)
    return tmp_path


def test_a_fastembed_index_is_searched_by_meaning_while_ollama_is_configured(
    built_with_fastembed: Path,
):
    found = sweep("gains per antenna", scopes=["notes"], named=True, bundle=None)

    hits = found.groups["notes"]
    assert hits
    assert all(hit.result.dense_score is not None for hit in hits)
    assert found.unembedded == ()


def test_an_index_built_with_another_model_is_named_with_the_command_that_rebuilds_it(
    built_with_fastembed: Path,
):
    found = sweep("gains per antenna", scopes=["notes"], named=True, bundle=None)

    assert found.other_models == (
        OtherModel(
            name="notes",
            built_backend="fastembed",
            built_model="BAAI/bge-small-en-v1.5",
            configured_backend="ollama",
            configured_model="embeddinggemma-2:570m",
            resolution="kennis corpus index --collection notes",
        ),
    )


def test_an_index_built_with_the_configured_model_is_not_named(
    built_with_fastembed: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "fastembed")
    monkeypatch.setenv("KENNIS_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.delenv("KENNIS_EMBEDDING_BASE_URL")

    found = sweep("gains per antenna", scopes=["notes"], named=True, bundle=None)

    assert found.other_models == ()


def test_a_scope_whose_model_cannot_embed_the_question_is_matched_by_keywords(
    built_with_fastembed: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(embedding_module, "_FastembedEmbedder", Unreachable)

    with caplog.at_level(logging.WARNING, logger="kennis.retrieval"):
        found = sweep("gains per antenna", scopes=["notes"], named=True, bundle=None)

    hits = found.groups["notes"]
    assert hits
    assert all(hit.result.dense_score is None for hit in hits)
    [unembedded] = found.unembedded
    assert isinstance(unembedded, Unembedded)
    assert unembedded.name == "notes"
    assert "connection refused" in unembedded.reason
    assert any("connection refused" in record.getMessage() for record in caplog.records)


def test_the_command_line_names_the_other_model_and_its_command(
    built_with_fastembed: Path,
):
    result = CliRunner().invoke(
        main, ["search", "gains per antenna", "--collection", "notes"]
    )

    assert result.exit_code == 0, result.output
    assert "fastembed" in result.output
    assert "embeddinggemma-2:570m" in result.output
    assert "kennis corpus index --collection notes" in result.output


def test_a_configured_address_is_given_only_to_the_configured_backend():
    configured = EmbeddingSettings(
        backend="ollama", model="embeddinggemma-2:570m", base_url=OLLAMA_ADDRESS
    )
    elsewhere = EmbeddingSettings(
        backend="openai", model="text-embedding-3-large", base_url="http://openai.local"
    )

    assert address_for("fastembed", configured) is None
    assert address_for("ollama", configured) == OLLAMA_ADDRESS
    assert address_for("ollama", elsewhere) == resolve_host("ollama", None)
    assert address_for("openai", configured) is None


def test_fastembed_is_never_given_an_address():
    assert resolve_host("fastembed", OLLAMA_ADDRESS) is None


def test_the_log_records_everything_unless_asked_for_less():
    assert LoggingSettings().level == "debug"


TOKEN = "the-token"

NOTE = """\
---
title: Gains
owner: user
---

# Gains

Gains are solved per antenna and per interval.
"""


def test_a_search_inside_a_project_whose_index_is_fastembed_s_succeeds(
    built_with_fastembed: Path, monkeypatch: pytest.MonkeyPatch
):
    """Brian's case: the corpus reindexed with ollama, the project's own
    index still fastembed's, and the search run from inside the project."""
    project = built_with_fastembed / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    run = CliRunner()
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "fastembed")
    monkeypatch.setenv("KENNIS_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.delenv("KENNIS_EMBEDDING_BASE_URL")
    # Brian's setting: a project index with meaning, so it holds vectors.
    monkeypatch.setenv("KENNIS_RETRIEVAL_CONTEXT_METHOD", "hybrid")
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    (project / ".context" / "gains.md").write_text(NOTE, encoding="utf-8")
    indexed = run.invoke(main, ["context", "index"])
    assert indexed.exit_code == 0, indexed.output
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("KENNIS_EMBEDDING_MODEL", "embeddinggemma-2:570m")
    monkeypatch.setenv("KENNIS_EMBEDDING_BASE_URL", OLLAMA_ADDRESS)

    result = run.invoke(main, ["search", "gains per antenna"])

    assert result.exit_code == 0, result.output
    assert "kennis context index" in result.output
    # By meaning with its own model, not by keywords after a refusal.
    assert "could not be used" not in result.output


def test_the_window_names_the_other_model_and_its_command(
    built_with_fastembed: Path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi.testclient import TestClient

    from kennis.gui.app import build_app

    monkeypatch.setenv("KENNIS_STATE_DIR", str(built_with_fastembed / "state"))
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200

    page = client.get("/hits", params={"q": "gains per antenna", "scope": "notes"}).text

    assert "embeddinggemma-2:570m" in page, page
    assert "kennis corpus index --collection notes" in page


def test_a_refused_command_is_written_to_the_log_where_it_was_raised_and_shown(
    built_with_fastembed: Path, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING):
        result = CliRunner().invoke(
            main, ["search", "anything", "--collection", "literature"]
        )

    assert result.exit_code == 1
    refusals = [
        record for record in caplog.records if "literature" in record.getMessage()
    ]
    assert {record.name for record in refusals} >= {"kennis.cli", "kennis.service"}
    assert any(
        record.exc_info for record in refusals if record.name == "kennis.service"
    )
