"""The guided setup, as the engine describes it.

Concern #108's rule: the engine owns **what is asked** - the questions, their
order, their validation - and a front end owns **how**. So every test here
runs without a terminal, which is the property that makes the same setup
reachable from a GUI later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.setup import (
    Question,
    apply_answers,
    questions_for,
    setup_questions,
    validate_answer,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
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


def test_an_empty_answer_writes_nothing_for_that_key(isolated: Path):
    apply_answers({"embedding.backend": "", "chunking.size": "800"})

    written = (isolated / "config.toml").read_text(encoding="utf-8")
    assert "backend" not in written.replace("# backend", "")
    assert "size = 800" in written


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


def test_the_credentials_file_is_readable_only_by_its_owner(isolated: Path):
    apply_answers(
        {"embedding.backend": "openai", "embedding.api_key": "sk-notarealkey"}
    )

    mode = (isolated / "credentials.toml").stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)


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
    import os

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


def test_the_conversion_key_never_reaches_the_config_file(tmp_path: Path):
    import os

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
