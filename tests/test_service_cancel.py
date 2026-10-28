"""A task is cancelled through the service (Brian, 2026-10-27).

The service's half: the job, the request and the stream. What a cancelled
write leaves in the corpus is `test_cancelling.py`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine import cancelling
from kennis.engine.errors import TaskStopped
from kennis.engine.events import EventSink, Progress
from kennis.protocol.wire import load_error
from kennis.service.api import PREFIX
from kennis.service.app import build_service_app
from kennis.service.jobs import Jobs

WAIT = 30.0
TOKEN = "a-test-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


def until_cancelled(started: threading.Event, ran_on: list[int]):
    """Work that reports progress until it is stopped, as a long add does.
    It finishes by itself after `WAIT`, so a cancel that is not honoured
    fails the test rather than hanging it."""

    def work(events: EventSink) -> str:
        started.set()
        for step in range(int(WAIT * 20)):
            ran_on.append(step)
            events.emit(Progress(operation="add", completed=step, total=None))
            threading.Event().wait(0.05)
        return "ran to its end"

    return work


def test_a_running_task_stops_at_its_next_event():
    jobs = Jobs()
    started = threading.Event()
    steps: list[int] = []
    job = jobs.start("add", until_cancelled(started, steps))
    assert started.wait(WAIT)

    assert jobs.cancel(job)

    assert job.done.wait(WAIT)
    assert isinstance(job.error, TaskStopped)
    assert job.result is None
    assert len(steps) < WAIT * 20


def test_a_queued_task_cancelled_never_begins():
    jobs = Jobs()
    release = threading.Event()
    ahead = jobs.start("add", lambda events: release.wait(WAIT))
    ran = threading.Event()
    behind = jobs.start("sync", lambda events: ran.set())

    assert jobs.cancel(behind)
    release.set()

    assert behind.done.wait(WAIT)
    assert ahead.done.wait(WAIT)
    assert isinstance(behind.error, TaskStopped)
    assert not ran.is_set()


def test_a_finished_task_cannot_be_cancelled():
    jobs = Jobs()
    job = jobs.start("add", lambda events: "done")
    assert job.done.wait(WAIT)

    assert not jobs.cancel(job)
    assert job.result == "done"


def test_a_task_publishing_finishes_what_it_began():
    """Past the point of no return, a cancel is not honoured: the task's
    change is kept and it is reported as the change it is."""
    jobs = Jobs()
    publishing = threading.Event()
    asked = threading.Event()

    def work(events: EventSink) -> str:
        cancelling.past_cancelling()
        publishing.set()
        asked.wait(WAIT)
        events.emit(Progress(operation="add", completed=1, total=1))
        return "published"

    job = jobs.start("add", work)
    assert publishing.wait(WAIT)
    jobs.cancel(job)
    asked.set()

    assert job.done.wait(WAIT)
    assert job.error is None
    assert job.result == "published"


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return build_service_app(TOKEN, root, on_stop=lambda: None)


def test_a_cancel_request_stops_the_task_and_its_stream_says_so(app: FastAPI):
    client = TestClient(app)
    started = threading.Event()
    job = app.state.jobs.start("add", until_cancelled(started, []))
    assert started.wait(WAIT)

    answer = client.post(f"{PREFIX}/job/{job.id}/cancel", headers=BEARER)

    assert answer.status_code == 202
    assert answer.json() == {"cancelling": True}
    streamed = client.get(f"{PREFIX}/job/{job.id}/events", headers=BEARER).text
    last = json.loads(streamed.strip().splitlines()[-1].removeprefix("data: "))
    assert isinstance(load_error(last["error"]), TaskStopped)


def test_cancelling_a_finished_task_says_it_was_not(app: FastAPI):
    client = TestClient(app)
    job = app.state.jobs.start("add", lambda events: "done")
    assert job.done.wait(WAIT)

    answer = client.post(f"{PREFIX}/job/{job.id}/cancel", headers=BEARER)

    assert answer.status_code == 200
    assert answer.json() == {"cancelling": False}


def test_cancelling_a_task_nobody_knows_is_refused(app: FastAPI):
    answer = TestClient(app).post(f"{PREFIX}/job/nothing/cancel", headers=BEARER)

    assert answer.status_code == 404
