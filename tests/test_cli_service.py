"""`kennis service watch`: following a task the person stopped watching (14c).

Ctrl-C in a command stops the watching and leaves the task running in the
service, and says which command follows it again. This is that command.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from in_process import InProcessServices
from kennis.cli.__main__ import main
from kennis.engine.errors import InputError

WAIT = 30.0


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return root


def test_watching_a_task_follows_it_to_its_end(
    corpus: Path, service_in_this_process: InProcessServices
):
    jobs = service_in_this_process.app(corpus).state.jobs
    job = jobs.start("index", lambda events: None)

    result = CliRunner().invoke(main, ["service", "watch", job.id])

    assert result.exit_code == 0, result.output
    assert "Finished" in result.output
    assert "index" in result.output.lower()


def test_watching_a_task_that_failed_says_why_and_fails(
    corpus: Path, service_in_this_process: InProcessServices
):
    def refused(events: object) -> None:
        raise InputError("the reason it failed", resolution="kennis corpus status")

    jobs = service_in_this_process.app(corpus).state.jobs
    job = jobs.start("index", refused)
    assert job.done.wait(WAIT)

    result = CliRunner().invoke(main, ["service", "watch", job.id])

    assert result.exit_code != 0
    assert "the reason it failed" in result.output
    assert "kennis corpus status" in result.output


def test_watching_a_task_the_service_does_not_know_says_so(corpus: Path):
    result = CliRunner().invoke(main, ["service", "watch", "nothing"])

    assert result.exit_code != 0
    assert "nothing" in result.output


def test_the_status_lists_the_unfinished_tasks(
    corpus: Path,
    service_in_this_process: InProcessServices,
    monkeypatch: pytest.MonkeyPatch,
):
    """Where a detached task's id can be found again."""
    import kennis.cli.commands.service as service_command
    from kennis.protocol.record import ServiceRecord

    release = threading.Event()
    jobs = service_in_this_process.app(corpus).state.jobs
    job = jobs.start("index", lambda events: release.wait(WAIT))
    record = ServiceRecord(
        address="http://testserver/",
        token="t",
        pid=1,
        started=datetime(2026, 1, 1).astimezone(),
        version="0",
        corpus=str(corpus),
    )
    monkeypatch.setattr(service_command, "find_service", lambda root: record)
    monkeypatch.setattr(
        service_command, "hello", lambda found: {"busy": True, "kennis": "0"}
    )
    try:
        result = CliRunner().invoke(main, ["service", "status"])
    finally:
        release.set()

    assert result.exit_code == 0, result.output
    assert job.id in result.output
    assert f"kennis service watch {job.id}" in result.output


def test_ctrl_c_in_a_command_leaves_its_task_running_and_names_the_watch(
    corpus: Path,
    service_in_this_process: InProcessServices,
    monkeypatch: pytest.MonkeyPatch,
):
    """The interrupt reaches the command while it follows the task's
    events; the command exits 130 and says how to follow the task again,
    and the task finishes in the service regardless (Brian's default 3)."""
    from kennis.cli.sink import DisplaySink
    from kennis.engine.events import Event

    def interrupted(self: DisplaySink, event: Event) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(DisplaySink, "emit", interrupted)

    source = corpus.parent / "trees.md"
    source.write_text("# Trees\n\nAbout trees.\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["corpus", "add", "-n", str(source)])

    assert result.exit_code == 130, result.output
    named = re.search(r"kennis service watch ([\w-]+)", result.output)
    assert named is not None, result.output
    job = service_in_this_process.app(corpus).state.jobs.get(named.group(1))
    assert job is not None, (named.group(1), result.output)
    assert job.done.wait(WAIT)
    assert len(sorted((corpus / "notes").rglob("*.md"))) == 1
