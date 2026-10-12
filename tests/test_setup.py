"""The guided setup, as the engine describes it.

Concern #108's rule: the engine owns **what is asked** - the questions, their
order, their validation - and a front end owns **how**. So every test here
runs without a terminal, which is the property that makes the same setup
reachable from a GUI later.
"""

from __future__ import annotations

import inspect
import os
import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel

from kennis.engine import setup
from kennis.engine.settings import Settings, credential
from kennis.engine.setup import (
    Question,
    apply_answers,
    credential_status,
    questions_for,
    setup_questions,
    validate_answer,
)
from platforms import needs_file_modes


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    # These modules are about what the settings layer reads, so the
    # suite-wide `offline_embedding` default must not be in the
    # environment they read. Removed after it, never in place of it.
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    return tmp_path / "config"


def by_key(key: str) -> Question:
    for question in setup_questions():
        if question.key == key:
            return question
    raise AssertionError(f"no question for '{key}'")


# ---------------------------------------------------------------------------
# What is asked
# ---------------------------------------------------------------------------


def test_nothing_in_the_catalogue_prompts_or_prints(capsys: pytest.CaptureFixture[str]):
    """The whole point of the split. An engine that prompted could not be
    driven by a form, a test, or an MCP client."""
    questions_for({})
    apply_answers({"embedding.backend": "none"})

    written = capsys.readouterr()
    assert written.out == "" and written.err == ""


def test_every_question_names_a_real_setting():
    """A question for a key the model does not have would be silently
    unwritable: `apply_answers` would validate it and nothing would read it."""
    from kennis.engine.settings import Settings

    for question in setup_questions():
        if question.kind == "secret":
            continue
        section, _, field = question.key.partition(".")
        assert section in Settings.model_fields, question.key
        annotation = Settings.model_fields[section].annotation
        assert annotation is not None
        assert field in annotation.model_fields, question.key


def test_a_choice_question_carries_the_values_it_accepts():
    """Derived from the `Literal` on the model, so they cannot drift from
    what it really takes."""
    backend = by_key("embedding.backend")

    assert backend.kind == "choice"
    assert set(backend.options) == {"fastembed", "ollama", "openai", "none"}


def test_a_bounded_question_carries_its_bounds():
    chunking = by_key("chunking.size")

    assert chunking.kind == "integer"
    assert chunking.minimum is not None and chunking.maximum is not None
    assert chunking.minimum < chunking.maximum


def test_each_question_offers_the_value_currently_in_effect():
    """So that re-running the setup and pressing return throughout changes
    nothing, which is what makes it safe to re-run at all."""
    assert by_key("embedding.backend").current == "fastembed"


def test_the_current_value_follows_the_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "ollama")

    assert by_key("embedding.backend").current == "ollama"


# ---------------------------------------------------------------------------
# What is asked depends on what was answered
# ---------------------------------------------------------------------------


def test_a_hosted_backend_asks_for_a_key_and_a_local_one_does_not():
    """`config init` must not hold the knowledge that openai needs a key and
    fastembed does not - that is a property of the backend, and a GUI that
    re-derived it would be re-implementing this file."""
    hosted = [
        question.key for question in questions_for({"embedding.backend": "openai"})
    ]
    local = [
        question.key for question in questions_for({"embedding.backend": "fastembed"})
    ]

    assert any(question.endswith("api_key") for question in hosted), hosted
    assert not any(question.endswith("api_key") for question in local), local


def test_keeping_a_backend_still_asks_what_that_backend_needs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """An empty answer means "unchanged", not "answered with nothing".

    Read the other way, a re-run in which the user keeps `openai` asks
    neither for the model nor for the key, so there is no way to change an
    API key through the setup at all.
    """
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[embedding]\nbackend = "openai"\n', encoding="utf-8"
    )

    asked = [question.key for question in questions_for({"embedding.backend": ""})]

    assert "embedding.api_key" in asked, asked
    assert "embedding.model" in asked, asked


def test_a_daemon_backend_asks_where_the_daemon_is():
    asked = [
        question.key for question in questions_for({"embedding.backend": "ollama"})
    ]

    assert "embedding.base_url" in asked


def test_turning_embedding_off_asks_nothing_more_about_it():
    """A lexical-only install should not be walked through a model name and
    a vector width it will never use."""
    asked = [question.key for question in questions_for({"embedding.backend": "none"})]

    assert not any(question.startswith("embedding.") for question in asked[1:])


def asked_under(backend: str) -> dict[str, Question]:
    return {
        question.key: question
        for question in questions_for({"embedding.backend": backend})
    }


@pytest.mark.parametrize(
    ("backend", "model"),
    [
        # Written by hand rather than read from the table, so a wrong entry
        # there is not agreed with by its own test (#373).
        ("ollama", "nomic-embed-text"),
        ("openai", "text-embedding-3-small"),
    ],
)
def test_another_backend_offers_its_own_model(backend: str, model: str):
    """A model name means something only to its backend, so the one in force
    belongs to fastembed and offering it under another failed at the next
    index. The value in force stays `current`, because that is what a front
    end compares an answer with to say what changed. Concern #441."""
    asked = asked_under(backend)

    assert asked["embedding.model"].suggested == model
    assert asked["embedding.model"].current == "BAAI/bge-small-en-v1.5"


def test_the_width_of_a_vector_is_never_asked():
    """The model fixes it and no backend is sent it (Brian, 2026-10-12)."""
    assert not any(
        question.key == "embedding.dimensions" for question in setup_questions()
    )


def test_the_backend_in_force_offers_the_model_in_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Including one that is not the default: it was chosen for this backend."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[embedding]\nbackend = "openai"\nmodel = "text-embedding-3-large"\n',
        encoding="utf-8",
    )

    assert asked_under("openai")["embedding.model"].suggested == (
        "text-embedding-3-large"
    )


def test_going_back_to_the_local_backend_offers_its_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[embedding]\nbackend = "openai"\nmodel = "text-embedding-3-small"\n',
        encoding="utf-8",
    )

    assert asked_under("fastembed")["embedding.model"].suggested == (
        "BAAI/bge-small-en-v1.5"
    )


def test_a_width_left_in_an_old_file_is_dropped_by_the_next_write(isolated: Path):
    """A section model ignores a key it no longer has, so the file still
    loads; every write renders the model's own keys, so it then goes."""
    isolated.mkdir(parents=True, exist_ok=True)
    (isolated / "config.toml").write_text(
        "[embedding]\ndimensions = 384\n", encoding="utf-8"
    )

    apply_answers({"chunking.size": "900"})

    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert "dimensions" not in written["embedding"]


def test_a_question_with_no_backend_offers_what_is_in_force():
    for question in setup_questions():
        if question.kind != "secret" and not question.when:
            assert question.suggested == question.current, question.key


def test_a_condition_is_a_value_a_form_can_evaluate():
    """Not a callback. A GUI binds field visibility to this predicate and
    shows every question at once; a terminal walks the list and skips."""
    key_question = next(
        question for question in setup_questions() if question.key.endswith("api_key")
    )

    assert key_question.when == (("embedding.backend", "openai"),)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_value_outside_a_choice_is_refused_by_name():
    problem = validate_answer(by_key("embedding.backend"), "nonesuch")

    assert problem is not None
    assert "fastembed" in problem


def test_a_number_outside_its_range_is_refused():
    problem = validate_answer(by_key("chunking.size"), "0")

    assert problem is not None


def test_a_number_that_is_not_a_number_is_refused():
    problem = validate_answer(by_key("chunking.size"), "large")

    assert problem is not None


def test_a_good_answer_has_no_problem():
    assert validate_answer(by_key("embedding.backend"), "ollama") is None
    assert validate_answer(by_key("chunking.size"), "800") is None


def test_an_empty_answer_means_keep_what_is_there():
    """Pressing return through the whole setup must change nothing."""
    assert validate_answer(by_key("embedding.backend"), "") is None


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def test_applying_writes_a_config_file_that_loads_back(isolated: Path):
    from kennis.engine.settings import load_settings

    apply_answers({"embedding.backend": "ollama", "chunking.size": "800"})

    assert (isolated / "config.toml").is_file()
    settings = load_settings()
    assert settings.embedding.backend == "ollama"
    assert settings.chunking.size == 800


def test_an_empty_answer_keeps_the_value_in_the_file(isolated: Path):
    apply_answers({"embedding.backend": "ollama"})

    apply_answers({"embedding.backend": "", "chunking.size": "800"})

    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert written["embedding"]["backend"] == "ollama"
    assert written["chunking"]["size"] == 800


def every_default() -> dict[str, dict[str, object]]:
    """Each section's defaults, from its own model, which reads no
    environment."""
    defaults: dict[str, dict[str, object]] = {}
    for section, field in Settings.model_fields.items():
        model = field.annotation
        assert isinstance(model, type) and issubclass(model, BaseModel)
        defaults[section] = model().model_dump()
    return defaults


def test_every_write_leaves_every_setting_in_the_file(isolated: Path):
    """The value a person accepted is the value saved, default or not, and
    a complete file is one that can be synced (Brian, 2026-10-12)."""
    apply_answers({"chunking.size": "800"})

    expected = every_default()
    expected["chunking"]["size"] = 800
    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert written == expected


def test_an_environment_override_is_not_written_into_the_file(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """An exported variable is a one-off. Written into the file it would
    outlive the shell that set it, and travel wherever the file is synced."""
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "ollama")

    apply_answers({"chunking.size": "800"})

    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert written["embedding"]["backend"] == "fastembed"


def test_a_secret_never_reaches_the_config_file(isolated: Path):
    """It goes to `credentials.toml`, which `settings.py` names and nothing
    reads back."""
    apply_answers(
        {"embedding.backend": "openai", "embedding.api_key": "sk-notarealkey"}
    )

    assert "sk-notarealkey" not in (isolated / "config.toml").read_text(
        encoding="utf-8"
    )
    assert "sk-notarealkey" in (isolated / "credentials.toml").read_text(
        encoding="utf-8"
    )


@needs_file_modes
def test_the_credentials_file_is_readable_only_by_its_owner(isolated: Path):
    apply_answers(
        {"embedding.backend": "openai", "embedding.api_key": "sk-notarealkey"}
    )

    mode = (isolated / "credentials.toml").stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)


def test_the_credentials_file_is_where_the_platform_protects_it(isolated: Path):
    """The part of the guarantee that holds on every platform.

    `chmod` is a no-op on Windows, so kennis cannot restrict the file
    itself there and relies on the config directory - which is under the
    user's profile and whose ACL denies exactly what 0600 denies. That is
    only true while the file stays in the config directory, which is what
    this asserts. Concern #389."""
    apply_answers(
        {"embedding.backend": "openai", "embedding.api_key": "sk-notarealkey"}
    )

    written = isolated / "credentials.toml"

    assert written.is_file()
    assert written.parent == isolated
    # And the call that would restrict it is still made, so the guarantee
    # is the platform's only where the platform gives kennis no choice.
    source = inspect.getsource(setup)
    assert "chmod(0o600)" in source.replace(" ", "")


def test_applying_a_bad_answer_refuses_before_writing(isolated: Path):
    from kennis.engine.errors import SettingsError

    with pytest.raises(SettingsError):
        apply_answers({"chunking.size": "0"})

    assert not (isolated / "config.toml").exists()


def test_rerunning_keeps_what_was_not_asked_about(isolated: Path):
    apply_answers({"embedding.backend": "ollama", "chunking.size": "800"})
    apply_answers({"chunking.size": "900"})

    from kennis.engine.settings import load_settings

    settings = load_settings()
    assert settings.chunking.size == 900
    # Not reset to the default by a second run that did not mention it.
    assert settings.embedding.backend == "ollama"


# ---------------------------------------------------------------------------
# The conversion backend
# ---------------------------------------------------------------------------


def test_choosing_hosted_conversion_asks_for_its_key():
    """Same shape as the embedding backend: the knowledge that datalab needs
    a credential and mineru does not is a property of the backend."""
    hosted = [
        question.key for question in questions_for({"conversion.backend": "datalab"})
    ]
    local = [
        question.key for question in questions_for({"conversion.backend": "mineru"})
    ]

    assert "conversion.api_key" in hosted, hosted
    assert "conversion.api_key" not in local, local


def test_the_datalab_key_is_written_under_its_own_variable(tmp_path: Path):
    """`credential("DATALAB_API_KEY")` is what reads it back, so the name the
    setup files it under is the name the converter looks for."""

    os.environ["KENNIS_CONFIG_DIR"] = str(tmp_path)
    try:
        apply_answers(
            {"conversion.backend": "datalab", "conversion.api_key": "dl-notarealkey"}
        )
        written = (tmp_path / "credentials.toml").read_text(encoding="utf-8")
    finally:
        del os.environ["KENNIS_CONFIG_DIR"]

    assert "DATALAB_API_KEY" in written
    assert "dl-notarealkey" in written


@pytest.fixture
def no_key_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment wins in `credential`, so a key exported in the shell
    running the suite would answer for the file being tested."""
    for variable in ("OPENAI_API_KEY", "MY_OWN_KEY", "ANOTHER_KEY"):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.usefixtures("no_key_in_the_environment")
def test_the_embedding_key_is_written_under_the_variable_it_is_read_from():
    """`embedding.api_key_env` names the variable embedding reads. Filing
    the key under `OPENAI_API_KEY` regardless left it where nothing looked,
    and the setup reported success. Concern #440."""
    apply_answers({"embedding.api_key_env": "MY_OWN_KEY"})

    apply_answers({"embedding.backend": "openai", "embedding.api_key": "sk-mine"})

    assert credential("MY_OWN_KEY") == "sk-mine"
    assert credential("OPENAI_API_KEY") == ""
    assert credential_status("embedding.api_key").is_set is True


@pytest.mark.usefixtures("no_key_in_the_environment")
def test_a_variable_named_in_the_same_answers_is_the_one_written():
    """The answers are validated as a whole before anything is written, so
    the key belongs under the variable those answers produce, not the one
    in force before them."""
    apply_answers({"embedding.api_key_env": "MY_OWN_KEY"})

    apply_answers(
        {
            "embedding.backend": "openai",
            "embedding.api_key_env": "ANOTHER_KEY",
            "embedding.api_key": "sk-mine",
        }
    )

    assert credential("ANOTHER_KEY") == "sk-mine"
    assert credential("MY_OWN_KEY") == ""


@pytest.mark.usefixtures("no_key_in_the_environment")
def test_a_new_key_replaces_one_already_in_the_file(isolated: Path):
    """`credential` takes the first section holding the name, so a key filed
    under any other section than the one it was in before would sit behind
    the old value rather than replace it."""
    isolated.mkdir(parents=True, exist_ok=True)
    (isolated / "credentials.toml").write_text(
        '[embedding]\nOPENAI_API_KEY = "sk-old"\n', encoding="utf-8"
    )

    apply_answers({"embedding.backend": "openai", "embedding.api_key": "sk-new"})

    assert credential("OPENAI_API_KEY") == "sk-new"


def test_the_conversion_key_never_reaches_the_config_file(tmp_path: Path):

    os.environ["KENNIS_CONFIG_DIR"] = str(tmp_path)
    try:
        apply_answers(
            {"conversion.backend": "datalab", "conversion.api_key": "dl-notarealkey"}
        )
        written = (tmp_path / "config.toml").read_text(encoding="utf-8")
    finally:
        del os.environ["KENNIS_CONFIG_DIR"]

    assert "dl-notarealkey" not in written
    assert 'backend = "datalab"' in written


def test_a_datalab_user_is_asked_which_mode_to_pay_for():
    """The mode is a price, and `config init` is where a datalab user is
    making price decisions. Asked only of them: a mineru user choosing a
    setting mineru ignores would be answering a question about nothing.
    Concern #147."""
    from kennis.engine.setup import questions_for

    for_datalab = [
        question.key for question in questions_for({"conversion.backend": "datalab"})
    ]
    for_mineru = [
        question.key for question in questions_for({"conversion.backend": "mineru"})
    ]

    assert "conversion.mode" in for_datalab
    assert "conversion.mode" not in for_mineru


def test_the_mode_question_is_asked_before_the_key_is_typed():
    """Both are consequences of choosing datalab, and the order a person
    reads them in is the order they are asked. The key is the last thing
    anybody wants to retype, so it comes after the cheap choice."""
    from kennis.engine.setup import questions_for

    keys = [q.key for q in questions_for({"conversion.backend": "datalab"})]

    assert keys.index("conversion.mode") < keys.index("conversion.api_key")


def test_a_setup_that_changes_nothing_writes_every_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Accepting every value is a choice of every value. This reverses the
    rule that wrote nothing for it (Brian, 2026-10-12), and with it the
    0-byte `config.toml` that rule once produced."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))

    apply_answers({})

    written = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert written == every_default()


def test_an_answer_left_empty_does_not_rewrite_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A re-run that changes nothing writes the same file again."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path))
    apply_answers({"chunking.size": "900"})
    before = (tmp_path / "config.toml").read_bytes()

    apply_answers({"chunking.size": ""})

    assert (tmp_path / "config.toml").read_bytes() == before
