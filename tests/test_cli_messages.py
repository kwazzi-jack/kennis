"""How much advice the command line prints, by choice (Brian, 2026-10-27).

`terminal.messages` is `all`, `warnings` or `errors`. It hides `hint:`
lines, then `warning:` lines too; never an `error:`, never the remedy
printed under one, and never a report.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli import display, sink
from kennis.cli.__main__ import main
from kennis.engine.events import Diagnostic, Severity
from kennis.engine.refusals import SameContent


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path


@pytest.fixture(autouse=True)
def every_message_again() -> Iterator[None]:
    """The level is module state, set by `main`; a test calling `display`
    directly must not leave it for the next."""
    yield
    display.set_messages("all")


def configured(tmp_path: Path, text: str) -> None:
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    (folder / "config.toml").write_text(text, encoding="utf-8")


def messages(level: str) -> str:
    return f'[terminal]\nmessages = "{level}"\n'


def test_by_default_a_warning_and_its_hint_are_shown():
    """The baseline the other tests hide things from: with no configuration
    file, `config show` warns that it prints the defaults and names the
    command that writes one."""
    shown = CliRunner().invoke(main, ["config", "show"])

    assert shown.exit_code == 0, shown.output
    assert "warning: no configuration file" in shown.output
    assert "hint: run `kennis config init`" in shown.output


def test_warnings_hides_hints_and_keeps_warnings_and_the_report(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KENNIS_TERMINAL_MESSAGES", "warnings")
    shown = CliRunner().invoke(main, ["config", "show"])

    assert shown.exit_code == 0, shown.output
    assert "warning: no configuration file" in shown.output
    assert "hint:" not in shown.output
    assert "[retrieval]" in shown.output


def test_errors_hides_warnings_and_hints_and_keeps_the_report(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KENNIS_TERMINAL_MESSAGES", "errors")
    shown = CliRunner().invoke(main, ["config", "show"])

    assert shown.exit_code == 0, shown.output
    assert "warning:" not in shown.output
    assert "hint:" not in shown.output
    assert "[retrieval]" in shown.output


def test_errors_keeps_an_error_and_its_way_out(tmp_path: Path):
    """The remedy under an `error:` is part of the error: hiding it would
    leave a failure with no command to resolve it."""
    configured(tmp_path, messages("errors"))
    failed = CliRunner().invoke(main, ["corpus", "status"])

    assert failed.exit_code == 1
    assert "error: there is no kennis corpus" in failed.output
    assert "hint: run `kennis corpus init`" in failed.output
    assert "full detail in" in failed.output


def test_a_configuration_that_will_not_load_shows_every_message(tmp_path: Path):
    """`messages = "errors"` in a file that will not load is not read: the
    unknown section is named by a `warning:` line before the command fails
    on the same file, and hiding it would hide why."""
    configured(tmp_path, messages("errors") + "[nonsense]\nkey = 1\n")
    shown = CliRunner().invoke(main, ["corpus", "status"])

    assert "warning:" in shown.output
    assert "which kennis does not read" in shown.output


def test_an_error_diagnostics_resolution_survives_errors(
    capsys: pytest.CaptureFixture[str],
):
    """A diagnostic reaches the terminal through `DisplaySink`, which is
    also how a service task's diagnostics arrive at the client."""
    display.set_messages("errors")
    with sink.DisplaySink() as shown:
        shown.emit(
            Diagnostic(
                severity=Severity.ERROR,
                detail=SameContent(document_id="trees"),
                resolution="kennis corpus remove trees",
            )
        )
        shown.emit(
            Diagnostic(
                severity=Severity.WARNING,
                detail=SameContent(document_id="oaks"),
                resolution="kennis corpus remove oaks",
            )
        )
        shown.emit(
            Diagnostic(
                severity=Severity.HINT,
                detail=SameContent(document_id="elms"),
            )
        )

    printed = capsys.readouterr().out
    assert "error:" in printed
    assert "kennis corpus remove trees" in printed
    assert "oaks" not in printed
    assert "elms" not in printed


def test_a_refused_item_keeps_its_way_out_when_only_errors_are_shown(
    capsys: pytest.CaptureFixture[str],
):
    """A failed item is a failure of the add, and the commands under the
    report are what resolve it."""
    from kennis.cli.adding import _report_remedies
    from kennis.engine.corpus.add import AddOutcome, AddReport
    from kennis.engine.events import Outcome
    from kennis.engine.refusals import NoIdentity

    display.set_messages("errors")
    _report_remedies(
        AddReport(
            outcomes=[
                AddOutcome(
                    identifier="scan.pdf",
                    outcome=Outcome.FAILED,
                    refusal=NoIdentity(named="scan.pdf"),
                )
            ],
            elapsed_seconds=0.0,
        )
    )

    assert "kennis corpus add -n scan.pdf" in capsys.readouterr().out


def test_a_cancelled_task_is_said_as_cancelled_and_exits_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Not `error:`: the person asked for it. 130, as an interrupted
    command exits."""
    from kennis.client import api
    from kennis.engine.errors import TaskStopped

    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0

    def stopped(*arguments: object, **keywords: object) -> object:
        raise TaskStopped()

    monkeypatch.setattr(api, "call", stopped)
    result = run.invoke(main, ["remember", "Oaks lose their leaves."])

    assert result.exit_code == 130, result.output
    assert "Cancelled: nothing was changed" in result.output
    assert "error:" not in result.output
