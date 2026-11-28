"""`kennis config info` says what a setting is.

Brian, 2026-11-28: a command that gives a setting's description, its type
and the values it may take, "similar to help in python", from the same
descriptions and types the settings page draws. The expectations below are
written by hand rather than read from the settings model: a test that
compared the command with the model would pass for any model at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.setup import apply_answers


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    monkeypatch.setenv("COLUMNS", "200")
    return tmp_path / "config"


def info(*arguments: str) -> str:
    result = CliRunner().invoke(main, ["config", "info", *arguments])
    assert result.exit_code == 0, result.output
    return result.output


def facts(output: str) -> dict[str, str]:
    """Each `label  value` line under a setting, as label -> value."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        label, _, value = line.strip().partition(" ")
        if label in {"type", "values", "default", "current", "applies"}:
            found[label] = value.strip()
    return found


def test_a_number_says_its_description_type_range_and_default():
    output = info("embedding.batch_size")

    assert output.splitlines()[0].strip() == "embedding.batch_size"
    assert "Texts per backend request." in output
    assert facts(output) == {
        "type": "whole number",
        "values": "1 to 1024",
        "default": "64",
        "current": "64",
        "applies": "when embedding.backend is fastembed, ollama or openai",
    }


def test_a_choice_names_every_value_it_may_take():
    stated = facts(info("logging.level"))

    assert stated["type"] == "one of the values"
    assert stated["values"] == "debug | info | warning | error"
    assert stated["default"] == "debug"
    assert "applies" not in stated


def test_the_current_value_is_the_one_in_force():
    assert (
        CliRunner()
        .invoke(main, ["config", "set", "logging.level", "warning"])
        .exit_code
        == 0
    )

    stated = facts(info("logging.level"))

    assert (stated["default"], stated["current"]) == ("debug", "warning")


def test_a_section_describes_each_of_its_settings_once():
    """`embedding.model` is asked under each backend; it is one setting."""
    output = info("embedding")

    headings = [
        line.strip() for line in output.splitlines() if line.startswith("embedding.")
    ]
    assert headings == [
        "embedding.backend",
        "embedding.model",
        "embedding.normalise",
        "embedding.batch_size",
        "embedding.base_url",
        "embedding.api_key_env",
        "embedding.api_key",
    ]


def test_a_secret_is_never_shown():
    apply_answers(
        {"embedding.backend": "openai", "embedding.api_key": "sk-kept-private"}
    )

    output = info("embedding.api_key")

    assert "sk-kept-private" not in output
    assert facts(output)["current"] == "(set)"


def test_every_setting_is_described_with_no_key():
    """Those the settings page does not offer too: they are settings a
    reader may ask about."""
    output = info()

    headings = {
        line.strip()
        for line in output.splitlines()
        if line and not line.startswith(" ")
    }
    assert {
        "corpus.root",
        "backup.folder",
        "logging.level",
        "embedding.model",
    } <= headings


def test_an_unknown_setting_is_refused_with_where_to_look():
    result = CliRunner().invoke(main, ["config", "info", "embedding.nonesuch"])

    assert result.exit_code == 1
    assert "no setting 'embedding.nonesuch'" in result.output
    assert "kennis config show" in result.output
