"""A command waiting for a busy service of another build says so.

Brian's trial (2026-11-25): `kennis service watch <task>`, typed with the
installed kennis while the checkout's service converted a textbook, showed
nothing at all - it was waiting for the task to end before replacing the
service (#537), and only `open` and `gui` said so. A Ctrl-C there ended the
wait, not the task.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from in_process import InProcessServices
from kennis import __version__
from kennis.cli.__main__ import main
from kennis.client import connection, process
from kennis.protocol.record import ServiceRecord
from kennis.render.words import waiting_for_another_version

# Port 1 on the loopback: nothing listens, so whatever the command does
# after the wait fails at once rather than reaching anything.
RECORD = ServiceRecord(
    address="http://127.0.0.1:1/",
    token="token",
    pid=1,
    started=datetime(2026, 11, 1, tzinfo=UTC),
    version="0.0.1",
    corpus="/corpus",
)


@pytest.fixture
def busy_then_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A service of version 0.0.1 busy for one look, then one of this
    client's own build."""
    monkeypatch.setattr(process, "build_of_this_process", lambda: "loaded")
    monkeypatch.setattr(process, "_BUSY_POLL_SECONDS", 0)
    monkeypatch.setattr(process, "find_service", lambda root: RECORD)
    answers: Iterator[dict[str, object]] = iter(
        [
            {"kennis": "0.0.1", "build": "other", "busy": True},
            {"kennis": __version__, "build": "loaded", "busy": False},
        ]
    )
    monkeypatch.setattr(process, "hello", lambda record: next(answers))


def test_a_wait_is_told_to_the_listener_when_no_caller_asked(
    busy_then_replaced: None, tmp_path: Path
):
    told: list[str] = []
    process.tell_of_waiting(told.append)

    assert process.ensure_service(tmp_path) == RECORD

    assert told == ["0.0.1"]


def test_a_caller_s_own_listener_is_told_instead(
    busy_then_replaced: None, tmp_path: Path
):
    registered: list[str] = []
    own: list[str] = []
    process.tell_of_waiting(registered.append)

    process.ensure_service(tmp_path, on_waiting=own.append)

    assert own == ["0.0.1"]
    assert registered == []


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return root


def test_any_command_says_it_is_waiting(
    busy_then_replaced: None,
    corpus: Path,
    service_in_this_process: InProcessServices,
    monkeypatch: pytest.MonkeyPatch,
):
    """Through the command line's own group, as `service watch` reached it.
    The suite's connection skips `ensure_service`, so this one goes through
    it first, as `connection.connect` does, and then to the in-process
    service, which has no such task."""

    def connect(corpus_root: Path) -> httpx.Client:
        process.ensure_service(corpus_root)
        return service_in_this_process.connect(corpus_root)

    monkeypatch.setattr(connection, "connect", connect)

    result = CliRunner().invoke(main, ["service", "watch", "b76593a612f1"])

    # The terminal wraps the line, so the words are compared, not the breaks.
    expected = waiting_for_another_version("0.0.1", __version__)
    assert " ".join(expected.split()) in " ".join(result.output.split())
