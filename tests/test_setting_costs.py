"""What changing a setting costs, as engine data (#410).

One of four things, and a setting may cost more than one: the next
search, the next add, a rebuild of every index, or sending document text
off this machine. Keyed by value as well as by key, because only some
backends send anything away. The words are in `render/`, so the command
line says the same as the window.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.setting_costs import COSTLESS, costs_of
from kennis.engine.setup import credential_status, setup_questions
from kennis.render.settings import describe_cost, describe_costs

# Written by hand (#373): every key's cost for an ordinary value.
EXPECTED = {
    "embedding.backend": ("rebuild",),
    "embedding.model": ("rebuild",),
    # The host is absent from the binding, so a moved daemon changes no
    # vector; it changes where the next query is embedded.
    "embedding.base_url": ("next_search",),
    "embedding.api_key": ("next_search",),
    "conversion.backend": ("next_add",),
    "conversion.mode": ("next_add",),
    "conversion.api_key": ("next_add",),
    "retrieval.corpus_method": ("next_search",),
    "retrieval.default_top_k": ("next_search",),
    "chunking.size": ("rebuild",),
}


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    return tmp_path


@pytest.mark.parametrize(("key", "costs"), list(EXPECTED.items()))
def test_each_setting_costs_what_was_written_down(key: str, costs: tuple[str, ...]):
    assert costs_of(key, "an ordinary value") == costs


def test_every_question_has_a_cost_or_is_named_as_having_none():
    """A setting added to the catalogue with no cost fails here, rather
    than reaching a page that cannot say what changing it does."""
    for question in setup_questions():
        assert question.key in EXPECTED or question.key in COSTLESS, question.key


def test_the_corpus_root_is_the_one_without():
    assert frozenset({"corpus.root"}) == COSTLESS
    with pytest.raises(KeyError):
        costs_of("corpus.root", "/elsewhere")


@pytest.mark.parametrize(
    ("key", "value"),
    [("embedding.backend", "openai"), ("conversion.backend", "datalab")],
)
def test_a_hosted_backend_sends_text_away(key: str, value: str):
    assert "leaves_machine" in costs_of(key, value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("embedding.backend", "fastembed"),
        ("embedding.backend", "ollama"),
        ("embedding.backend", "none"),
        ("conversion.backend", "mineru"),
    ],
)
def test_a_local_backend_does_not(key: str, value: str):
    assert "leaves_machine" not in costs_of(key, value)


def test_every_cost_has_words():
    for cost in ("next_search", "next_add", "rebuild", "leaves_machine"):
        assert describe_cost(cost)  # type-checked: an unworded case fails mypy


def test_costs_read_as_one_line():
    line = describe_costs(("next_add", "leaves_machine"))

    assert describe_cost("next_add") in line
    assert describe_cost("leaves_machine") in line


# ---------------------------------------------------------------------------
# The command line says it too
# ---------------------------------------------------------------------------


def test_config_set_says_what_the_change_costs():
    told = CliRunner().invoke(main, ["config", "set", "chunking.size", "900"])

    assert told.exit_code == 0, told.output
    assert describe_costs(costs_of("chunking.size", "900")) in told.output


def test_config_set_says_a_hosted_backend_sends_text_away():
    told = CliRunner().invoke(main, ["config", "set", "conversion.backend", "datalab"])

    assert told.exit_code == 0, told.output
    assert describe_cost("leaves_machine") in told.output


# ---------------------------------------------------------------------------
# A credential: its variable, and whether it is set
# ---------------------------------------------------------------------------


def test_a_credential_is_named_by_the_variable_it_is_read_from(
    monkeypatch: pytest.MonkeyPatch,
):
    status = credential_status("conversion.api_key")

    assert status.variable == "DATALAB_API_KEY"
    assert status.is_set is False

    monkeypatch.setenv("DATALAB_API_KEY", "a-key")
    assert credential_status("conversion.api_key").is_set is True


def test_the_embedding_key_follows_the_configured_variable(
    monkeypatch: pytest.MonkeyPatch,
):
    """Embedding reads `embedding.api_key_env`, so that is the name the
    reader is told - whatever the setup writes to."""
    assert credential_status("embedding.api_key").variable == "OPENAI_API_KEY"

    monkeypatch.setenv("KENNIS_EMBEDDING_API_KEY_ENV", "MY_KEY")
    monkeypatch.setenv("MY_KEY", "set")
    status = credential_status("embedding.api_key")

    assert status.variable == "MY_KEY"
    assert status.is_set is True


def test_a_status_never_carries_the_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATALAB_API_KEY", "sk-secret-value")
    status = credential_status("conversion.api_key")

    assert "sk-secret-value" not in repr(status)


def test_config_set_says_when_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
):
    """It printed "Set" while `config get` went on showing the variable's
    value, as the window already said and the command line did not."""
    monkeypatch.setenv("KENNIS_CHUNKING_SIZE", "500")

    told = CliRunner().invoke(main, ["config", "set", "chunking.size", "800"])

    assert told.exit_code == 0, told.output
    assert "KENNIS_CHUNKING_SIZE" in told.output
