"""The settings layer: what can be tuned, and where an answer comes from.

Precedence is environment, then the configuration file, then the field's
default. The environment is read by **exact name** rather than by splitting
on a delimiter, because splitting silently loses any key whose own name
contains the delimiter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.settings import (
    Settings,
    config_dir,
    config_path,
    config_template,
    load_settings,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No test reads the developer's own configuration.

    Through the same override users get, so the isolation mechanism is the
    one that is actually supported rather than a test-only back door.
    """
    directory = tmp_path / "config"
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(directory))
    return directory


def write_config(directory: Path, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.toml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_settings_load_with_no_file_and_no_environment():
    settings = load_settings()

    assert settings.embedding.backend == "fastembed"
    assert settings.retrieval.default_top_k > 0


def test_the_defaults_are_the_values_the_engine_already_uses():
    """A default that disagrees with the constant it replaces would change
    behaviour silently the moment settings are wired in."""
    from kennis.engine.rag.chunking import ChunkParameters

    settings = load_settings()

    assert settings.chunking.size == ChunkParameters().size
    assert settings.chunking.overlap == ChunkParameters().overlap


# ---------------------------------------------------------------------------
# Where an answer comes from
# ---------------------------------------------------------------------------


def test_the_file_overrides_a_default(isolated: Path):
    write_config(isolated, '[embedding]\nbackend = "ollama"\n')

    assert load_settings().embedding.backend == "ollama"


def test_the_environment_overrides_the_file(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    write_config(isolated, '[embedding]\nbackend = "ollama"\n')
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "openai")

    assert load_settings().embedding.backend == "openai"


def test_an_unset_key_keeps_its_default_when_others_are_set(isolated: Path):
    write_config(isolated, '[embedding]\nbackend = "ollama"\n')

    settings = load_settings()

    assert settings.embedding.backend == "ollama"
    assert settings.embedding.model == Settings().embedding.model


# ---------------------------------------------------------------------------
# Exact-name environment reading
# ---------------------------------------------------------------------------


def test_a_key_whose_name_contains_an_underscore_is_read(
    monkeypatch: pytest.MonkeyPatch,
):
    """The reason the environment source is written by hand.

    With pydantic-settings' `env_nested_delimiter="_"`, this variable splits
    as embedding.api.key.env, matches nothing, and is dropped in silence -
    no error, no warning, the field keeps its default, and a user who set it
    has no way to find out why it did nothing.
    """
    monkeypatch.setenv("KENNIS_EMBEDDING_API_KEY_ENV", "MY_OWN_KEY")

    assert load_settings().embedding.api_key_env == "MY_OWN_KEY"


def test_a_numeric_setting_is_converted_from_its_text(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KENNIS_RETRIEVAL_DEFAULT_TOP_K", "25")

    assert load_settings().retrieval.default_top_k == 25


def test_an_environment_variable_naming_nothing_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KENNIS_EMBEDDING_NOSUCHKEY", "whatever")

    assert load_settings().embedding.backend == "fastembed"


def test_an_invalid_value_is_refused_by_name(monkeypatch: pytest.MonkeyPatch):
    from kennis.engine.errors import SettingsError

    monkeypatch.setenv("KENNIS_RETRIEVAL_DEFAULT_TOP_K", "not a number")

    with pytest.raises(SettingsError) as raised:
        load_settings()

    assert "default_top_k" in str(raised.value)


# ---------------------------------------------------------------------------
# Where the files live
# ---------------------------------------------------------------------------


def test_the_config_directory_can_be_overridden(isolated: Path):
    assert config_dir() == isolated


def test_the_config_file_sits_in_that_directory(isolated: Path):
    assert config_path() == isolated / "config.toml"


def test_the_default_directory_is_the_platform_one(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("KENNIS_CONFIG_DIR", raising=False)

    assert config_dir().name == "kennis"


# ---------------------------------------------------------------------------
# The generated template
# ---------------------------------------------------------------------------


def test_the_template_is_valid_toml():
    import tomllib

    tomllib.loads(config_template())


def test_every_section_appears_in_the_template():
    template = config_template()

    for section in Settings.model_fields:
        assert f"[{section}]" in template


def test_every_key_appears_commented_at_its_default():
    """Commented rather than live: writing defaults as active values freezes
    them at install time, so a later kennis that improves a default would
    never reach anyone who ran `config init`."""
    template = config_template()

    assert "# backend = " in template
    assert "\nbackend = " not in template


def test_a_closed_set_lists_its_options():
    assert "Options: fastembed | ollama | openai" in config_template()


def test_a_bounded_number_states_its_range():
    assert "Range: 1-100" in config_template()


def test_a_free_form_key_carries_an_example():
    template = config_template()

    assert "Examples:" in template
    assert "BAAI/bge-small-en-v1.5" in template


def test_the_template_carries_no_credential():
    """`config show` writes this to standard output by design, and a user
    debugging will paste it into an issue. A key among the settings would
    make every printing path need redaction."""
    template = config_template().lower()

    assert "api_key =" not in template
    assert "secret" not in template


def test_the_options_come_from_the_model_rather_than_from_prose():
    """Generated from the schema so they cannot drift from what the model
    actually accepts - which a hand-written comment would."""
    from typing import get_args

    from kennis.engine.settings import EmbeddingSettings

    backends = get_args(EmbeddingSettings.model_fields["backend"].annotation)
    for backend in backends:
        assert backend in config_template()
