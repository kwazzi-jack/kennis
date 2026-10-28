"""The client's side of a call: a read answered, a job followed (14c).

Against the service's application in this process, through the same
`connect` every command uses, which the autouse `service_in_this_process`
fixture binds to an in-process application for the test's corpus (#503).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from in_process import InProcessServices
from kennis.cli.__main__ import main
from kennis.client import calls, connection
from kennis.client.calls import JobDetached, Notice, Started, call, watch
from kennis.context import existing_corpus
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.collection import CollectionContents
from kennis.engine.errors import DocumentNotFound, TaskStopped
from kennis.engine.events import (
    Event,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Progress,
)
from kennis.holdings import contents_of
from kennis.protocol.progress import Began, Elapsed, Queued
from kennis.protocol.wire import Json, dump, dump_error
from kennis.service.jobs import CORPUS_LANE


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return root


def a_source(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\nAbout {name}.\n", encoding="utf-8")
    return path


class Recorded:
    """Every event a job reported, in order."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


def test_a_read_answers_as_its_declared_type(corpus: Path):
    answered = call(
        connection.connect(corpus),
        "contents",
        {"collection": "notes"},
        returns=CollectionContents,
    )

    assert answered.result == contents_of(existing_corpus(), "notes")
    assert isinstance(answered.result, CollectionContents)


def test_a_job_is_followed_to_its_end_and_its_events_reach_the_sink(
    corpus: Path, tmp_path: Path
):
    recorded = Recorded()

    answered = call(
        connection.connect(corpus),
        "add",
        {
            "destination": "notes",
            "identifiers": [str(a_source(tmp_path, "one.md"))],
            "options": AddOptions(),
        },
        returns=AddReport,
        events=recorded,
    )

    assert isinstance(answered.result, AddReport)
    assert [outcome.identifier for outcome in answered.result.outcomes] == [
        str(a_source(tmp_path, "one.md"))
    ]
    kinds = [type(event) for event in recorded.events]
    assert kinds[0] is ItemStarted
    assert ItemFinished in kinds
    assert kinds[-1] is OperationFinished
    assert answered.restored == []


def test_a_refusal_is_raised_as_the_error_it_was(corpus: Path):
    with pytest.raises(DocumentNotFound):
        call(
            connection.connect(corpus),
            "remove_document",
            {"collection": "notes", "handle": "absent"},
            returns=object,
        )


def test_a_job_behind_another_says_so_before_it_begins(
    corpus: Path, tmp_path: Path, service_in_this_process: InProcessServices
):
    told: list[Notice] = []
    app = service_in_this_process.app(corpus)
    release = threading.Event()
    app.state.jobs.start("index", lambda events: release.wait(30), lane=CORPUS_LANE)

    def released_once_the_add_waits() -> None:
        # On the second job's arrival, not after a fixed time: a slow
        # runner submitted the add after a 0.2 s timer had already let the
        # first job go, and the add had nothing to wait behind (#533).
        deadline = time.monotonic() + 30
        while len(app.state.jobs.unfinished()) < 2 and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        release.set()

    threading.Thread(target=released_once_the_add_waits, daemon=True).start()

    call(
        connection.connect(corpus),
        "add",
        {
            "destination": "notes",
            "identifiers": [str(a_source(tmp_path, "two.md"))],
            "options": AddOptions(),
        },
        returns=AddReport,
        events=Recorded(),
        on_waiting=told.append,
    )

    assert isinstance(told[0], Started)
    assert told[1:] == [Queued(ahead=1, behind="index"), Began()]


class ScriptedService(httpx.Client):
    """The two requests `watch` makes, scripted: the stream replays the
    job's history from its start on every connection, as the service's
    does, and ends with the task's outcome. A cancel stops the task at the
    step after the one last streamed when it was asked, as the service's
    stops at the next event (or `lag` steps on, for a task slow to reach
    one); a task with no step left finishes.

    Not the in-process application: its client reads a streamed answer to
    the end before handing over a line, so a watcher there sees a task's
    events only after it has finished.
    """

    def __init__(self, steps: int, *, lag: int = 1) -> None:
        super().__init__()
        self.steps = steps
        self.lag = lag
        self.cancels = 0
        self.connections = 0
        self._streamed = -1
        self._stops_at: int | None = None

    def messages(self, connection: object, job: str) -> Iterator[dict[str, Json]]:
        self.connections += 1
        for step in range(self.steps):
            if step == self._stops_at:
                yield {"error": dump_error(TaskStopped())}
                return
            self._streamed = max(self._streamed, step)
            yield {"event": dump(Progress(operation="add", completed=step, total=None))}
            yield {"event": dump(Elapsed(seconds=float(step)))}
        yield {"result": dump("ran to its end"), "restored": dump([])}

    def post(self, url: httpx.URL | str, *args: Any, **keywords: Any) -> httpx.Response:
        assert url == "job/a-job/cancel", url
        self.cancels += 1
        self._stops_at = self._streamed + self.lag
        return httpx.Response(202, json={"cancelling": True})


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedService:
    service = ScriptedService(steps=20)
    monkeypatch.setattr(calls, "_messages", service.messages)
    return service


class InterruptedAt:
    """Records each event, and raises Ctrl-C at the ones named."""

    def __init__(self, *at: int) -> None:
        self.at = set(at)
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)
        if len(self.events) in self.at:
            raise KeyboardInterrupt


def test_an_interrupt_while_following_cancels_the_task(scripted: ScriptedService):
    """Ctrl-C cancels (Brian, 2026-10-27, reversing 14c's default 3), and
    the client follows the task to what it ended as."""
    with pytest.raises(TaskStopped):
        watch(scripted, "a-job", returns=str, events=InterruptedAt(2))

    assert scripted.cancels == 1


def test_the_events_before_an_interrupt_are_not_handed_on_twice(
    scripted: ScriptedService,
):
    """The stream an interrupt broke is read again from the job's start; the
    clock's ticks are not in the history and are not counted."""
    shown = InterruptedAt(3)

    with pytest.raises(TaskStopped):
        watch(scripted, "a-job", returns=str, events=shown)

    steps = [event.completed for event in shown.events if isinstance(event, Progress)]
    assert steps == list(range(len(steps)))
    assert scripted.connections == 2


def test_a_second_interrupt_detaches_and_names_the_job(scripted: ScriptedService):
    """Pressed again while the task is still on its way to a point that can
    stop: the watching ends, and the cancel already asked stands."""
    scripted.lag = 5
    with pytest.raises(JobDetached) as detached:
        watch(scripted, "a-job", returns=str, events=InterruptedAt(1, 2))

    assert "a-job" in str(detached.value.resolution)
    assert scripted.cancels == 1


def test_a_task_that_finished_first_is_reported_as_finished(
    scripted: ScriptedService,
):
    """Interrupted after its last event: the cancel arrives too late, and
    the result is what the task did."""
    followed = watch(scripted, "a-job", returns=str, events=InterruptedAt(20))

    assert followed.result == "ran to its end"


def test_every_command_reaches_the_service_in_this_process(corpus: Path):
    """The harness's own guard: a connection is to this process's
    application, never to a started service."""
    assert connection.connect.__module__ != "kennis.client.connection"
    assert connection.connect(corpus).base_url.host == "testserver"
