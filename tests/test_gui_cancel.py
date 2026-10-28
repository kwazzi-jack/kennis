"""The window cancels a task (Brian, 2026-10-27: "This was something missing
from the gui as well which was canceling activities").

A form on the job's panel, so it works without a script; tested by
submitting the form the page drew (#432).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.errors import TaskStopped
from kennis.engine.events import EventSink, Progress
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.service.jobs import Job

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
WAIT = 30.0


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def a_running_job(app: FastAPI) -> Job:
    started = threading.Event()

    def work(events: EventSink) -> None:
        started.set()
        for step in range(int(WAIT * 20)):
            events.emit(Progress(operation="sync", completed=step, total=None))
            threading.Event().wait(0.05)

    job: Job = app.state.jobs.start("sync", work)
    assert started.wait(WAIT)
    return job


def cancel_form(page: str) -> BeautifulSoup | None:
    form = BeautifulSoup(page, "html.parser").select_one("form.job-cancel")
    return form


def test_a_running_task_s_panel_offers_to_cancel_it(app: FastAPI, client: TestClient):
    job = a_running_job(app)
    try:
        panel = client.get(f"/job/{job.id}", headers=HTMX).text
        form = cancel_form(panel)

        assert form is not None
        assert form["method"] == "post"
        assert form["action"] == f"/job/{job.id}/cancel"
        assert words.CANCEL_TASK in form.get_text()
    finally:
        app.state.jobs.cancel(job)


def test_the_strip_offers_it_on_every_page(app: FastAPI, client: TestClient):
    job = a_running_job(app)
    try:
        assert cancel_form(client.get("/").text) is not None
    finally:
        app.state.jobs.cancel(job)


def test_a_finished_task_offers_no_cancel(app: FastAPI, client: TestClient):
    job: Job = app.state.jobs.start("sync", lambda events: None)
    assert job.done.wait(WAIT)

    assert cancel_form(client.get(f"/job/{job.id}", headers=HTMX).text) is None


def test_the_drawn_form_cancels_the_task(app: FastAPI, client: TestClient):
    job = a_running_job(app)
    form = cancel_form(client.get(f"/job/{job.id}", headers=HTMX).text)
    assert form is not None

    answer = client.post(str(form["action"]), headers=HTMX)

    assert answer.status_code == 200
    assert words.CANCELLING in answer.text
    assert job.done.wait(WAIT)
    assert isinstance(job.error, TaskStopped)


def test_without_a_script_the_form_leads_to_the_task_s_page(
    app: FastAPI, client: TestClient
):
    job = a_running_job(app)

    answer = client.post(f"/job/{job.id}/cancel")

    assert answer.status_code == 303
    assert answer.headers["location"] == f"/job/{job.id}"
    assert job.done.wait(WAIT)


def test_a_cancelled_task_says_so_and_what_it_kept(app: FastAPI, client: TestClient):
    job = a_running_job(app)
    app.state.jobs.cancel(job)
    assert job.done.wait(WAIT)

    outcome = client.get(f"/job/{job.id}/outcome").text
    headline = BeautifulSoup(outcome, "html.parser").select_one("p")

    assert headline is not None
    assert headline.get_text(" ", strip=True).startswith(
        words.cancelled(TaskStopped.default_message)
    )
    assert headline["data-state"] == "attention"
    activity = client.get("/activity").text
    assert words.JOB_CANCELLED in activity


def test_cancelling_a_task_nobody_knows_says_so(client: TestClient):
    answer = client.post("/job/nothing/cancel", headers=HTMX)

    assert words.NO_SUCH_JOB in answer.text
