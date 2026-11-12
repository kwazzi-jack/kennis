"""`retrieval.scores`: how a search shows how well each hit matched (#599).

Read by the command line, where `--scores` overrides it for one search, and
by the MCP search tools. The window always draws levels.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.mcp.tools.search import search


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    source = tmp_path / "Gains.md"
    source.write_text("# Gains\n\nAntenna gains drift slowly.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


def searched(*arguments: str) -> str:
    result = CliRunner().invoke(main, ["search", "antenna gains", *arguments])
    assert result.exit_code == 0, result.output
    return result.output


def test_levels_by_default(corpus: Path):
    shown = searched()
    assert "keywords: very high" in shown
    assert "bm25=" not in shown


def test_the_setting_shows_the_raw_scores(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_RETRIEVAL_SCORES", "raw")

    shown = searched()

    assert "bm25=" in shown
    assert "keywords:" not in shown


def test_the_option_overrides_the_setting(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_RETRIEVAL_SCORES", "raw")

    shown = searched("--scores", "human")

    assert "keywords: very high" in shown


def test_the_setting_can_hide_them(corpus: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KENNIS_RETRIEVAL_SCORES", "none")

    shown = searched()

    assert "keywords:" not in shown
    assert "bm25=" not in shown


def test_an_agent_sees_what_the_setting_says(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    assert "keywords: very high" in search("antenna gains", ["notes"])

    monkeypatch.setenv("KENNIS_RETRIEVAL_SCORES", "raw")

    assert "bm25=" in search("antenna gains", ["notes"])
