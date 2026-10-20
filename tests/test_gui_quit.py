"""Unit 11a2: a browser-tab application, and how it stops.

kennis's window is a tab in the person's own browser (#420). Closing a
tab does not end the process that serves it, so the bar carries **Quit**,
a POST that stops the service that serves it (14b); the next command
starts another.

Three things are worth holding here. Quit is a write in the sense that
matters - it ends the process - so it is a POST behind the token like
every other one. It refuses while a job runs, because a job is a daemon
thread that may hold the corpus lock half way through a commit and
stopping the process kills it there. And the page it answers with must
need nothing more from the server, because by the time the browser asks
for a stylesheet the server is gone.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.protocol.record import ServiceRecord

TOKEN = "a-test-token"


class Stops:
    """Counts the times the application asked to be stopped."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


@pytest.fixture
def stops() -> Stops:
    return Stops()


@pytest.fixture
def app(stops: Stops) -> FastAPI:
    return build_app(TOKEN, on_quit=stops)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


def admitted(client: TestClient) -> TestClient:
    assert client.get("/static/kennis.css", params={"token": TOKEN}).status_code == 200
    return client


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


def test_quit_answers_a_page_and_then_asks_to_stop(client: TestClient, stops: Stops):
    answer = admitted(client).post("/quit")

    assert answer.status_code == 200
    assert words.STOPPED in answer.text
    assert stops.calls == 1


def test_the_stopped_page_needs_nothing_more_from_the_server(client: TestClient):
    """The server is shutting down as this page arrives, so a
    stylesheet or script it links to would be fetched from nothing and
    the page would render bare. Everything it needs is inline."""
    page = admitted(client).post("/quit").text

    # A `data:` address is carried in the page, so the icon is allowed.
    fetched = [
        href
        for href in re.findall(r"<link\b[^>]*\bhref=\"([^\"]*)\"", page)
        if not href.startswith("data:")
    ]
    assert fetched == []
    assert not re.search(r"<link\b(?![^>]*\bhref=)", page)
    assert not re.search(r"<script\b[^>]*\bsrc=", page)
    assert "<style>" in page


def test_quit_is_not_a_get(client: TestClient, stops: Stops):
    """A GET that stops the process is one a prefetcher will follow."""
    assert admitted(client).get("/quit").status_code == 405
    assert stops.calls == 0


def test_quit_needs_the_token(client: TestClient, stops: Stops):
    """The route a hostile local process would most like to reach, on a
    shared machine where loopback is not private (#309)."""
    assert client.post("/quit").status_code == 401
    assert stops.calls == 0


def test_quit_refuses_while_a_job_runs(app: FastAPI, client: TestClient, stops: Stops):
    """A job is a daemon thread; stopping the process kills it wherever
    it is, which can be inside the corpus lock or half way through a
    commit. The refusal names what is running and does not stop."""
    admitted(client)
    holding = threading.Event()
    app.state.jobs.start("add", lambda events: holding.wait(10))
    try:
        answer = client.post("/quit")
    finally:
        holding.set()

    assert answer.status_code == 409
    assert words.QUIT_WHILE_RUNNING in answer.text
    assert stops.calls == 0


def test_quit_is_allowed_once_the_job_has_finished(
    app: FastAPI, client: TestClient, stops: Stops
):
    """One at a time, not never: the refusal is about a running job."""
    admitted(client)
    holding = threading.Event()
    earlier = app.state.jobs.start("add", lambda events: holding.wait(10))
    holding.set()
    assert earlier.done.wait(10)

    assert client.post("/quit").status_code == 200
    assert stops.calls == 1


def test_the_bar_carries_quit_as_a_plain_form(corpus: Path, client: TestClient):
    """A plain form posting to `/quit`, with no htmx: without a script
    it still stops, and the answer is a whole page rather than a
    fragment swapped into somewhere (#366, #412)."""
    page = admitted(client).get("/").text

    forms = re.findall(r"<form\b[^>]*\baction=\"/quit\"[^>]*>", page)
    assert len(forms) == 1
    assert re.search(r"\bmethod=\"post\"", forms[0])
    assert "hx-" not in forms[0]
    bar = page[page.index('<header class="bar">') : page.index("</header>")]
    assert 'action="/quit"' in bar


# ---------------------------------------------------------------------------
# The browser's own messages
# ---------------------------------------------------------------------------


def test_what_the_browser_prints_does_not_reach_kenniss_terminal(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
):
    """Brave wrote "Opening in existing browser session." and a zygote
    ERROR under kennis's address. A real child process stands in for it,
    because only a child inherits the descriptors - a Python write in
    this process would prove nothing about what a browser sees."""
    import os
    import subprocess
    import sys

    import kennis.gui.browser as serving

    def a_browser(url: str) -> bool:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; print('browser out'); sys.stderr.write('browser err')",
            ],
            check=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        return True

    monkeypatch.setattr(serving.webbrowser, "open", a_browser)

    # Written to the descriptors themselves: under `capfd` a `print`
    # goes to pytest's file directly and would pass with 1 and 2 left
    # pointing at the null device.
    os.write(1, b"kennis before\n")
    serving.open_quietly("http://127.0.0.1:1/")
    os.write(1, b"kennis after\n")
    os.write(2, b"kennis err after\n")
    captured = capfd.readouterr()

    assert "browser" not in captured.out + captured.err
    assert "kennis before" in captured.out and "kennis after" in captured.out
    assert "kennis err after" in captured.err


# ---------------------------------------------------------------------------
# `kennis gui`, a client of the service (14b)
# ---------------------------------------------------------------------------

RECORD = ServiceRecord(
    address="http://127.0.0.1:4242/",
    token="the-token",
    pid=1,
    started=datetime(2026, 1, 2, tzinfo=UTC),
    version="0",
    corpus="/a corpus",
)


def test_kennis_gui_opens_the_service_s_address_once_and_quietly(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    import kennis.client.process as process
    import kennis.gui.browser as browser

    quietly: list[str] = []
    loudly: list[str] = []
    monkeypatch.setattr(process, "ensure_service", lambda root, **_: RECORD)
    monkeypatch.setattr(browser, "open_quietly", quietly.append)
    # Replaced too, so that opening loudly fails this test rather than
    # starting the real browser.
    monkeypatch.setattr(browser.webbrowser, "open", loudly.append)

    result = CliRunner().invoke(main, ["gui"])

    assert result.exit_code == 0, result.output
    assert quietly == ["http://127.0.0.1:4242/?token=the-token&bundle="]
    assert quietly[0] in result.output
    assert loudly == []


def test_kennis_gui_without_a_browser_only_prints_the_address(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    import kennis.client.process as process
    import kennis.gui.browser as browser

    opened: list[str] = []
    monkeypatch.setattr(process, "ensure_service", lambda root, **_: RECORD)
    monkeypatch.setattr(browser, "open_quietly", opened.append)

    result = CliRunner().invoke(main, ["gui", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert opened == []
    assert "http://127.0.0.1:4242/?token=the-token&bundle=" in result.output


def test_kennis_gui_names_the_project_it_was_run_in(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The service is shared by every directory, so the tab is told which
    project it was opened from (#508); outside one it is told none, which
    the empty value says."""
    import kennis.client.process as process
    import kennis.gui.browser as browser

    opened: list[str] = []
    monkeypatch.setattr(process, "ensure_service", lambda root, **_: RECORD)
    monkeypatch.setattr(browser, "open_quietly", opened.append)
    project = tmp_path / "a project"
    (project / "deeper").mkdir(parents=True)
    monkeypatch.chdir(project)
    assert CliRunner().invoke(main, ["context", "init", "--here"]).exit_code == 0
    monkeypatch.chdir(project / "deeper")

    result = CliRunner().invoke(main, ["gui"])

    assert result.exit_code == 0, result.output
    (address,) = opened
    named = parse_qs(urlsplit(address).query, keep_blank_values=True)
    assert named["bundle"] == [str((project / ".context").resolve())]
