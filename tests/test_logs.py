"""The log file: what the report leaves out.

The report is for the person running the command; the log is for whoever is
debugging afterwards. Conflating them is the classic failure - user-facing
output emitted through `logging.info` means log levels start controlling the
interface.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kennis.engine.events import Diagnostic, ItemFinished, Outcome, Severity
from kennis.logs import LogSink, log_path, start_logging, stop_logging


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No test writes to the developer's own log."""
    directory = tmp_path / "state"
    monkeypatch.setenv("KENNIS_LOG_DIR", str(directory))
    yield directory
    stop_logging()


def written(directory: Path) -> str:
    path = directory / "kennis.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# ---------------------------------------------------------------------------
# Where it goes
# ---------------------------------------------------------------------------


def test_the_log_lives_where_the_platform_puts_state(isolated: Path):
    assert log_path() == isolated / "kennis.log"


def test_the_log_directory_is_created_on_demand(isolated: Path):
    start_logging()
    logging.getLogger("kennis").info("something happened")

    assert (isolated / "kennis.log").is_file()


def test_the_file_sink_is_always_on_rather_than_behind_a_flag(isolated: Path):
    """It is the thing you ask for when something went wrong, so it has to
    already exist by then."""
    start_logging()
    logging.getLogger("kennis").debug("a detail the report omits")

    assert "a detail the report omits" in written(isolated)


def test_nothing_is_written_to_standard_output(
    isolated: Path, capsys: pytest.CaptureFixture[str]
):
    """Under `kennis serve` stdout is the JSON-RPC wire. boepie was burned by
    a library writing INFO into it and the client answering `Invalid JSON`."""
    start_logging()
    logging.getLogger("kennis").warning("a warning")

    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# The event sink
# ---------------------------------------------------------------------------


def test_every_event_reaches_the_log(isolated: Path):
    """The log records what the report summarises: which documents were
    skipped and why each one, not the count."""
    start_logging()
    sink = LogSink()

    for number in range(3):
        sink.emit(
            ItemFinished(
                operation="add",
                item=f"paper{number}.pdf",
                outcome=Outcome.SKIPPED,
                reason="not a supported format",
            )
        )

    contents = written(isolated)
    for number in range(3):
        assert f"paper{number}.pdf" in contents


def test_the_reason_is_logged_not_just_the_outcome(isolated: Path):
    start_logging()

    LogSink().emit(
        ItemFinished(
            operation="add",
            item="one.pdf",
            outcome=Outcome.FAILED,
            reason="the converter produced nothing",
        )
    )

    assert "the converter produced nothing" in written(isolated)


def test_a_diagnostic_is_logged_at_its_severity(isolated: Path):
    start_logging()

    LogSink().emit(Diagnostic(severity=Severity.ERROR, message="something is wrong"))

    assert "ERROR" in written(isolated)


def test_the_sink_works_before_logging_is_started(isolated: Path):
    """A caller that never started logging must not crash on its first
    event - the sink is installed by the front end, and a library used
    directly has none."""
    LogSink().emit(Diagnostic(severity=Severity.WARNING, message="fine"))


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_the_log_rotates_rather_than_growing_without_bound(isolated: Path):
    start_logging(max_bytes=2048, backup_count=2)
    logger = logging.getLogger("kennis")

    for number in range(500):
        logger.info("a reasonably long line of log output number %d", number)

    assert list(isolated.glob("kennis.log*")) != [isolated / "kennis.log"]
    assert len(list(isolated.glob("kennis.log*"))) <= 3
