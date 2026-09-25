"""The settings layer: what can be tuned, and where an answer comes from.

Precedence is environment, then the configuration file, then the field's
default. The environment is read by **exact name** rather than by splitting
on a delimiter, because splitting silently loses any key whose own name
contains the delimiter.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from kennis.engine.settings import (
    ConversionSettings,
    Settings,
    config_dir,
    config_path,
    config_template,
    credential,
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
    # These modules are about what the settings layer reads, so the
    # suite-wide `offline_embedding` default must not be in the
    # environment they read. Removed after it, never in place of it.
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
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


# ---------------------------------------------------------------------------
# Reading a stored credential
# ---------------------------------------------------------------------------
#
# `config init` wrote credentials.toml from the first day it existed and
# nothing ever read it back, so a key someone typed into the setup had no
# effect on anything. Concern #131.


def test_a_stored_credential_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / "credentials.toml").write_text(
        '[embedding]\nOPENAI_API_KEY = "sk-stored"\n', encoding="utf-8"
    )

    assert credential("OPENAI_API_KEY") == "sk-stored"


def test_the_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A shell export, a CI secret and a `KENNIS_` override all arrive this
    way, and none of them should be shadowed by a file written months ago."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    (tmp_path / "credentials.toml").write_text(
        '[embedding]\nOPENAI_API_KEY = "sk-stored"\n', encoding="utf-8"
    )

    assert credential("OPENAI_API_KEY") == "sk-from-the-shell"


def test_a_credential_that_was_never_set_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)

    assert credential("DATALAB_API_KEY") == ""


def test_a_credentials_file_that_does_not_parse_is_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Every command would otherwise die on a file only one of them needs."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / "credentials.toml").write_text("not = = toml\n", encoding="utf-8")

    assert credential("OPENAI_API_KEY") == ""


def test_the_section_a_credential_sits_in_does_not_matter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The variable name is the identity. Which section the setup happened to
    file it under is an implementation detail of the writer."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / "credentials.toml").write_text(
        '[conversion]\nDATALAB_API_KEY = "dl-stored"\n', encoding="utf-8"
    )

    assert credential("DATALAB_API_KEY") == "dl-stored"


# ---------------------------------------------------------------------------
# Reading a credential from a .env file
# ---------------------------------------------------------------------------
#
# Brian keeps his Datalab key in `.env.keys`. A key may therefore arrive from
# four places, and which one wins has to be stated rather than emerge from
# the order the code happens to be written in. Concern #140.


def test_a_credential_in_env_keys_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env.keys").write_text(
        "DATALAB_API_KEY=dl-from-env-keys\n", encoding="utf-8"
    )

    assert credential("DATALAB_API_KEY") == "dl-from-env-keys"


def test_a_credential_in_a_plain_env_file_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DATALAB_API_KEY=dl-from-env\n", encoding="utf-8")

    assert credential("DATALAB_API_KEY") == "dl-from-env"


def test_every_source_in_order_of_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The one test that pins the order. Each source holds a *different*
    value, so removing any step of the chain changes the answer rather than
    leaving it accidentally right.

    Environment, then `.env.keys`, then `.env`, then `credentials.toml`.
    """
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    (tmp_path / ".env.keys").write_text("K=from-env-keys\n", encoding="utf-8")
    (tmp_path / ".env").write_text("K=from-env\n", encoding="utf-8")
    (tmp_path / "credentials.toml").write_text(
        '[conversion]\nK = "from-toml"\n', encoding="utf-8"
    )

    monkeypatch.setenv("K", "from-the-shell")
    assert credential("K") == "from-the-shell"

    monkeypatch.delenv("K")
    assert credential("K") == "from-env-keys"

    (tmp_path / ".env.keys").unlink()
    assert credential("K") == "from-env"

    (tmp_path / ".env").unlink()
    assert credential("K") == "from-toml"

    (tmp_path / "credentials.toml").unlink()
    assert credential("K") == ""


def test_an_env_file_in_the_working_directory_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """kennis is run from whatever directory the user is in, usually somebody
    else's checkout. A `.env` there belongs to that project, and reading it
    would let an arbitrary repository supply the key kennis uses to send a
    document to a third party. rules.md 4.5."""
    working = tmp_path / "somebody-elses-repo"
    working.mkdir()
    (working / ".env").write_text("DATALAB_API_KEY=dl-from-a-repo\n", encoding="utf-8")
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    monkeypatch.chdir(working)

    assert credential("DATALAB_API_KEY") == ""


def test_a_bare_name_with_no_value_is_not_a_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """dotenv represents a line that is just `KEY` as `None`, and a line that
    is `KEY=` as the empty string. Neither is a key; both must fall through
    to the next source rather than return as an answer."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env.keys").write_text("DATALAB_API_KEY\n", encoding="utf-8")
    (tmp_path / ".env").write_text("DATALAB_API_KEY=\n", encoding="utf-8")
    (tmp_path / "credentials.toml").write_text(
        '[conversion]\nDATALAB_API_KEY = "dl-stored"\n', encoding="utf-8"
    )

    assert credential("DATALAB_API_KEY") == "dl-stored"


MALFORMED_ENV: Final = 'DATALAB_API_KEY="unterminated\nnot a statement\n'


def test_an_env_file_that_does_not_parse_is_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Every command calls `credential`, so a file only one command needs
    must not be able to stop the rest."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env.keys").write_text(MALFORMED_ENV, encoding="utf-8")

    assert credential("DATALAB_API_KEY") == ""


def test_a_malformed_env_file_emits_no_log_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """python-dotenv reports a bad line through `logging.warning`. The
    suppression works by level, so the record is never created at all -
    a stronger statement than "it was not printed", and the one that can be
    checked in-process.

    Checking stdout and stderr here would prove nothing: pytest's logging
    plugin puts a handler on the root logger, so `logging.lastResort` never
    fires and nothing reaches stderr whether kennis suppresses it or not.
    That is how this test was hollow when first written.
    """
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env.keys").write_text(MALFORMED_ENV, encoding="utf-8")

    with caplog.at_level(logging.DEBUG):
        assert credential("DATALAB_API_KEY") == ""

    assert [record.name for record in caplog.records] == []


def test_a_malformed_env_file_prints_nothing_in_a_bare_process(tmp_path: Path):
    """The claim the suppression exists for, tested where it is true or
    false: a process with no logging configured, which is every real kennis
    invocation. There `logging.lastResort` sends a warning to stderr.

    A subprocess rather than a fixture because the condition *is* the absence
    of pytest's own logging handler.
    """
    (tmp_path / ".env.keys").write_text(MALFORMED_ENV, encoding="utf-8")
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            "from kennis.engine.settings import credential;"
            " print(repr(credential('DATALAB_API_KEY')))",
        ],
        env={
            **{k: v for k, v in os.environ.items() if k != "DATALAB_API_KEY"},
            "KENNIS_CONFIG_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip() == "''"
    assert finished.stderr == ""


def test_reading_an_env_file_does_not_alter_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`dotenv_values` is used rather than `load_dotenv` precisely so that
    the process environment is untouched. If the file leaked into
    `os.environ`, the environment-wins rule above would become an accident of
    which call happened first."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    (tmp_path / ".env.keys").write_text(
        "DATALAB_API_KEY=dl-from-env-keys\nOTHER=also-here\n", encoding="utf-8"
    )

    assert credential("DATALAB_API_KEY") == "dl-from-env-keys"
    assert "DATALAB_API_KEY" not in os.environ
    assert "OTHER" not in os.environ


def test_the_mode_setting_warns_that_changing_it_is_not_free():
    """A document already converted is cached by the server, but the mode is
    part of the cache key: re-adding the same paper at a different mode is
    charged in full. Measured - 7.6c for a 19-page paper already converted
    at `balanced`. Someone reading the setting is deciding whether to change
    it, and that is the moment the cost has to be stated. Concern #147."""
    description = ConversionSettings.model_fields["mode"].description or ""

    assert "again" in description.lower() or "re-convert" in description.lower()


def test_the_mode_setting_says_it_does_not_apply_to_the_default_backend():
    """A setting that silently does nothing is a promise. mineru ignores it."""
    description = ConversionSettings.model_fields["mode"].description or ""

    assert "mineru" in description.lower()


def test_no_setting_description_names_an_install_command():
    """A description is schema metadata and is written into `config.toml` as
    a comment, so a command inside one is a command a reader is told to run.
    Which install command is right depends on how kennis was installed, and
    only `Converter.install_hint()` knows. This has now escaped twice - into
    `converters.py` (#185) and into this description (#195) - so it is a test
    rather than a comment.
    """
    from kennis.engine.settings import Settings

    for section in Settings.model_fields.values():
        model = section.annotation
        assert model is not None
        for field in getattr(model, "model_fields", {}).values():
            description = field.description or ""
            assert "uv sync" not in description, description
            assert "uv tool install" not in description, description
            assert "pip install" not in description, description
