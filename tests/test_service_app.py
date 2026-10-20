"""The service's application, built in the test's own process (14b).

The window's pages and the clients' API in one application behind one
guard; no process is started here.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute
from starlette.types import Message, Receive, Scope, Send

from kennis import __version__
from kennis.cli.__main__ import main
from kennis.engine.errors import ServiceBusy
from kennis.protocol.wire import API_VERSION, load_error
from kennis.service.api import PREFIX
from kennis.service.app import CountingRequests, build_service_app
from kennis.service.idle import IdleTimer

TOKEN = "a-test-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return root


class Stops:
    def __init__(self) -> None:
        self.asked = threading.Event()

    def __call__(self) -> None:
        self.asked.set()


@pytest.fixture
def stops() -> Stops:
    return Stops()


@pytest.fixture
def app(corpus: Path, stops: Stops) -> FastAPI:
    return build_service_app(TOKEN, corpus, on_stop=stops)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def every_route(routes: Sequence[BaseRoute]) -> Iterator[APIRoute]:
    """Each route, inside the routers the application includes as well:
    FastAPI keeps an included router whole rather than copying its routes."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from every_route(included.routes)


def api_routes(app: FastAPI) -> list[APIRoute]:
    return [route for route in every_route(app.routes) if route.path.startswith(PREFIX)]


def test_the_api_is_under_its_version():
    assert f"/api/{API_VERSION}" == PREFIX


def test_hello_says_whose_corpus_and_which_kennis(client: TestClient, corpus: Path):
    answer = client.get(f"{PREFIX}/hello", headers=BEARER)

    assert answer.status_code == 200
    said = answer.json()
    assert said["kennis"] == __version__
    assert said["api"] == API_VERSION
    assert said["corpus"] == str(corpus)
    assert said["busy"] is False


def test_the_api_has_routes_to_check(app: FastAPI):
    """A walk over no routes passes for the wrong reason."""
    assert len(api_routes(app)) >= 2


def test_every_api_route_refuses_without_the_token(app: FastAPI, client: TestClient):
    for route in api_routes(app):
        for method in route.methods:
            answer = client.request(
                method, route.path.replace("{", "x").replace("}", "")
            )
            assert answer.status_code == 401, (method, route.path)


def test_a_wrong_bearer_token_is_refused(client: TestClient):
    answer = client.get(f"{PREFIX}/hello", headers={"Authorization": "Bearer wrong"})

    assert answer.status_code == 401


def test_another_scheme_is_not_a_token(client: TestClient):
    answer = client.get(f"{PREFIX}/hello", headers={"Authorization": f"Basic {TOKEN}"})

    assert answer.status_code == 401


def test_stop_asks_whoever_runs_the_server(client: TestClient, stops: Stops):
    answer = client.post(f"{PREFIX}/stop", headers=BEARER)

    assert answer.status_code == 200
    assert stops.asked.is_set()


def test_stop_is_refused_while_a_job_is_unfinished(
    app: FastAPI, client: TestClient, stops: Stops
):
    release = threading.Event()
    app.state.jobs.start("add", lambda events: release.wait(30))
    try:
        answer = client.post(f"{PREFIX}/stop", headers=BEARER)
    finally:
        release.set()

    assert answer.status_code == 409
    assert isinstance(load_error(answer.json()["error"]), ServiceBusy)
    assert not stops.asked.is_set()
    assert client.get(f"{PREFIX}/hello", headers=BEARER).json()["kennis"]


def test_hello_says_when_a_job_is_unfinished(app: FastAPI, client: TestClient):
    release = threading.Event()
    app.state.jobs.start("add", lambda events: release.wait(30))
    try:
        said = client.get(f"{PREFIX}/hello", headers=BEARER).json()
    finally:
        release.set()

    assert said["busy"] is True


def test_the_window_is_served_by_the_same_application(client: TestClient):
    assert client.get("/", params={"token": TOKEN}).status_code == 200


def test_an_open_request_is_counted_until_it_ends():
    """A page's event stream keeps the service for as long as it watches:
    the count is held across the whole of the inner application, which for
    a streamed answer is until its last byte is sent. Driven directly,
    because the test client gathers a stream before handing it over."""
    timer = IdleTimer(3600, lambda: False, lambda: None)
    seen: list[int] = []

    async def answering(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(timer.open_requests)

    async def nothing() -> Message:
        return {"type": "http.disconnect"}

    async def ignored(message: Message) -> None:
        pass

    counting = CountingRequests(answering, timer)
    asyncio.run(counting({"type": "http"}, nothing, ignored))
    timer.stop()

    assert seen == [1]
    assert timer.open_requests == 0


def test_the_service_counts_its_requests(corpus: Path):
    timer = IdleTimer(3600, lambda: False, lambda: None)
    app = build_service_app(TOKEN, corpus, idle=timer)
    timer.stop()

    assert any(entry.cls is CountingRequests for entry in app.user_middleware)


class CountingTimer(IdleTimer):
    """Records each touch and never fires."""

    def __init__(self) -> None:
        super().__init__(3600, lambda: False, lambda: None)
        self.touched = 0

    def touch(self) -> None:
        self.touched += 1


def test_a_job_s_beginning_and_end_are_activity(corpus: Path):
    timer = CountingTimer()
    app = build_service_app(TOKEN, corpus, idle=timer)

    job = app.state.jobs.start("add", lambda events: None)
    assert job.done.wait(30)

    # Submitted, then finished: the second is told just after `done`.
    deadline = time.monotonic() + 30
    while timer.touched < 2 and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert timer.touched == 2


def test_a_service_for_a_folder_that_is_no_corpus_refuses_to_start(tmp_path: Path):
    """Nothing to own: no lock taken, no record written, at once."""
    from kennis.protocol.record import is_held, record_path
    from kennis.protocol.spawn import NO_CORPUS
    from kennis.service.serve import run_service

    # On a thread with a bound, so a service that did start fails this
    # test rather than serving the empty folder until its idle timeout.
    statuses: list[int] = []
    attempt = threading.Thread(
        target=lambda: statuses.append(run_service(tmp_path)), daemon=True
    )
    attempt.start()
    attempt.join(10)

    assert statuses == [NO_CORPUS]
    assert not is_held(tmp_path)
    assert not record_path(tmp_path).exists()
