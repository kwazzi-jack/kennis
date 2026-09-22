"""`kennis config`, through the command line.

The engine half is `test_setup.py` and needs no terminal. This is the part
that only exists once there is one: prompting, the stdout/stderr split, and
what a person sees.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    return tmp_path / "config"


@pytest.fixture
def run() -> CliRunner:
    """A runner that keeps the two streams apart.

    `mix_stderr` defaults to joining them, which would make the one property
    `config show` exists to have untestable.
    """
    return CliRunner()


def streams(result: object) -> tuple[str, str]:
    return getattr(result, "stdout", ""), getattr(result, "stderr", "")


def settings_in(written: str) -> dict[str, str]:
    """Every key the file actually sets, flattened to `section.key`.

    The template leaves the `[section]` headers active and comments out the
    keys, so a file that sets nothing still parses as a handful of empty
    tables rather than as `{}`.
    """
    parsed = tomllib.loads(written)
    return {
        f"{section}.{key}": repr(value)
        for section, keys in parsed.items()
        if isinstance(keys, dict)
        for key, value in keys.items()
    }


# ---------------------------------------------------------------------------
# show, path, get, set
# ---------------------------------------------------------------------------


def test_show_writes_valid_toml_to_stdout(run: CliRunner):
    """`kennis config show > config.toml` has to produce a usable file."""
    result = run.invoke(main, ["config", "show"])

    assert result.exit_code == 0, result.output
    out, _ = streams(result)
    tomllib.loads(out)


def test_the_missing_file_warning_goes_to_stderr(run: CliRunner):
    """In the middle of stdout it would corrupt the redirect it warns about."""
    result = run.invoke(main, ["config", "show"])

    out, err = streams(result)
    assert "no configuration file" in err
    assert "no configuration file" not in out
    tomllib.loads(out)


def test_path_prints_where_the_file_would_be(run: CliRunner, isolated: Path):
    result = run.invoke(main, ["config", "path"])

    assert result.exit_code == 0, result.output
    assert str(isolated) in result.output


def test_get_names_a_setting_that_does_not_exist(run: CliRunner):
    result = run.invoke(main, ["config", "get", "embedding.nonesuch"])

    assert result.exit_code != 0
    assert "nonesuch" in result.output
    assert "backend" in result.output


def test_get_returns_one_value_plainly(run: CliRunner):
    """Plainly, so `$(kennis config get embedding.backend)` is the value and
    not a decorated line."""
    result = run.invoke(main, ["config", "get", "embedding.backend"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "fastembed"


def test_set_changes_one_value_and_leaves_the_rest(run: CliRunner, isolated: Path):
    assert run.invoke(main, ["config", "set", "chunking.size", "800"]).exit_code == 0
    assert (
        run.invoke(main, ["config", "set", "embedding.backend", "none"]).exit_code == 0
    )

    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert written["chunking"]["size"] == 800
    assert written["embedding"]["backend"] == "none"


def test_set_refuses_a_value_the_settings_would_reject(run: CliRunner, isolated: Path):
    result = run.invoke(main, ["config", "set", "chunking.size", "0"])

    assert result.exit_code != 0
    assert not (isolated / "config.toml").exists()


def test_a_number_is_written_as_a_number(run: CliRunner, isolated: Path):
    """A quoted number in a TOML file is a string, and the next load fails on
    it somewhere far from the command that wrote it."""
    run.invoke(main, ["config", "set", "chunking.size", "800"])

    assert "size = 800" in (isolated / "config.toml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_with_defaults_writes_the_commented_template(
    run: CliRunner, isolated: Path
):
    result = run.invoke(main, ["config", "init", "--defaults"])

    assert result.exit_code == 0, result.output
    written = (isolated / "config.toml").read_text(encoding="utf-8")
    assert "# backend" in written
    # Commented out, so a later kennis that improves a default still reaches
    # whoever ran this.
    assert settings_in(written) == {}


def test_pressing_return_throughout_changes_nothing(run: CliRunner, isolated: Path):
    """What makes the setup safe to re-run at all."""
    result = run.invoke(main, ["config", "init"], input="\n" * 20)

    assert result.exit_code == 0, result.output
    written = (isolated / "config.toml").read_text(encoding="utf-8")
    assert settings_in(written) == {}


def test_the_setup_asks_about_the_backend_first(run: CliRunner):
    """Everything else that is asked depends on the answer, so asking it
    anywhere but first would mean asking questions that the backend then
    makes irrelevant."""
    result = run.invoke(main, ["config", "init"], input="\n" * 20)

    positions = {
        key: result.output.find(key)
        for key in ("embedding.backend", "retrieval.corpus_method", "chunking.size")
    }
    assert -1 not in positions.values(), result.output
    assert positions["embedding.backend"] == min(positions.values())


def test_choosing_a_local_backend_never_asks_for_a_key(run: CliRunner):
    """The knowledge that openai needs one and fastembed does not lives in
    the engine, so this is checking that the command asks what it is told to
    rather than what it assumes."""
    result = run.invoke(main, ["config", "init"], input="fastembed\n" + "\n" * 20)

    assert "api_key" not in result.output


def test_choosing_a_hosted_backend_asks_for_a_key(run: CliRunner, isolated: Path):
    answers = "openai\n" + "text-embedding-3-small\n" + "sk-notarealkey\n" + "\n" * 20
    result = run.invoke(main, ["config", "init"], input=answers)

    assert result.exit_code == 0, result.output
    assert "api_key" in result.output


def test_a_key_is_never_echoed_or_written_to_the_config(run: CliRunner, isolated: Path):
    """It would otherwise sit in scrollback, in a screenshot, and in
    whatever the terminal logs."""
    answers = "openai\n" + "text-embedding-3-small\n" + "sk-notarealkey\n" + "\n" * 20
    result = run.invoke(main, ["config", "init"], input=answers)

    assert result.exit_code == 0, result.output
    assert "sk-notarealkey" not in result.output
    assert "sk-notarealkey" not in (isolated / "config.toml").read_text(
        encoding="utf-8"
    )
    assert "sk-notarealkey" in (isolated / "credentials.toml").read_text(
        encoding="utf-8"
    )


def test_a_rejected_answer_is_asked_again(run: CliRunner, isolated: Path):
    """Re-asking is an interaction and belongs here; a form would mark the
    field instead. Either way the engine only ever says why."""
    result = run.invoke(main, ["config", "init"], input="nonesuch\nnone\n" + "\n" * 20)

    assert result.exit_code == 0, result.output
    # Counted, not merely present: the options are listed with every prompt,
    # so any substring of them is in the output whether it was re-asked or
    # not. Twice is the whole claim.
    assert result.output.count("embedding.backend [") == 2, result.output
    assert "expected one of" in result.output
    written = tomllib.loads((isolated / "config.toml").read_text(encoding="utf-8"))
    assert written["embedding"]["backend"] == "none"


def test_the_count_is_of_what_was_written_not_what_was_asked(
    run: CliRunner, isolated: Path
):
    """Five questions are asked either way. Reporting five settings
    configured for a file that sets one is a claim about disk that is false.
    """
    kept = run.invoke(main, ["config", "init"], input="\n" * 20)
    assert kept.exit_code == 0, kept.output
    assert "Configured" not in kept.output
    assert "Changed nothing" in kept.output
    assert settings_in((isolated / "config.toml").read_text(encoding="utf-8")) == {}

    one = run.invoke(main, ["config", "init"], input="none\n" + "\n" * 20)
    assert one.exit_code == 0, one.output
    assert "Configured 1 setting" in one.output
    assert set(settings_in((isolated / "config.toml").read_text(encoding="utf-8"))) == {
        "embedding.backend"
    }


def test_the_setup_closes_by_naming_the_next_command(run: CliRunner):
    result = run.invoke(main, ["config", "init"], input="\n" * 20)

    assert "kennis corpus init" in result.output
