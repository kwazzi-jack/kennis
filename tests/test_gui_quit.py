"""Unit 11a2: a browser-tab application, and how it stops.

kennis's window is a tab in the person's own browser (#420). Closing a
tab does not end the process that serves it, so the bar carries **Quit**,
a POST that stops the server; Ctrl-C at the terminal still does too.

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
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.jobs import Jobs
from kennis.gui.serve import _wait_for_quit
from kennis.render.words import still_running_on_interrupt

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
# The launcher
# ---------------------------------------------------------------------------


def test_the_browser_is_opened_once_at_the_address_announced(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    import kennis.gui.serve as serving

    announced: list[str] = []
    opened: list[str] = []
    monkeypatch.setattr(serving.webbrowser, "open", opened.append)
    monkeypatch.setattr(serving, "_wait_for_quit", lambda *_: None)

    serving.run(announced.append)

    assert len(announced) == 1
    assert opened == announced


def test_no_browser_opens_nothing(corpus: Path, monkeypatch: pytest.MonkeyPatch):
    """Over `ssh -L` on a machine with no display, `webbrowser` does not
    fail: with `TERM` set it finds `www-browser`, `lynx` or `w3m` and
    runs a text browser in the terminal kennis is printing to."""
    import kennis.gui.serve as serving

    announced: list[str] = []
    opened: list[str] = []
    monkeypatch.setattr(serving.webbrowser, "open", opened.append)
    monkeypatch.setattr(serving, "_wait_for_quit", lambda *_: None)

    serving.run(announced.append, open_browser=False)

    assert len(announced) == 1
    assert opened == []


def test_quit_from_the_page_stops_a_real_server(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """End to end on a real uvicorn: the stopped page arrives, and then
    `run` returns. The order matters - stopping first would close the
    connection the page was travelling on."""
    import kennis.gui.serve as serving

    monkeypatch.setattr(serving.webbrowser, "open", lambda url: True)
    addresses: list[str] = []
    ready = threading.Event()

    def note(url: str) -> None:
        addresses.append(url)
        ready.set()

    runner = threading.Thread(target=serving.run, args=(note,), daemon=True)
    runner.start()
    assert ready.wait(10)

    with httpx.Client(timeout=10) as http:
        assert http.get(addresses[0]).status_code == 200
        answer = http.post(addresses[0].split("?")[0] + "quit")

    assert answer.status_code == 200
    assert words.STOPPED in answer.text
    runner.join(10)
    assert not runner.is_alive()


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

    import kennis.gui.serve as serving

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
    serving._open_quietly("http://127.0.0.1:1/")
    os.write(1, b"kennis after\n")
    os.write(2, b"kennis err after\n")
    captured = capfd.readouterr()

    assert "browser" not in captured.out + captured.err
    assert "kennis before" in captured.out and "kennis after" in captured.out
    assert "kennis err after" in captured.err


def test_run_opens_the_browser_quietly(corpus: Path, monkeypatch: pytest.MonkeyPatch):
    import kennis.gui.serve as serving

    quietly: list[str] = []
    loudly: list[str] = []
    monkeypatch.setattr(serving, "_open_quietly", quietly.append)
    # Replaced too, so that opening loudly fails this test rather than
    # starting the real browser.
    monkeypatch.setattr(serving.webbrowser, "open", loudly.append)
    monkeypatch.setattr(serving, "_wait_for_quit", lambda *_: None)

    serving.run(lambda url: None)

    assert len(quietly) == 1
    assert loudly == []


# ---------------------------------------------------------------------------
# Ctrl-C with a job running (#422)
# ---------------------------------------------------------------------------


class Interrupted:
    """An event whose waits are interrupted `times` times, then end."""

    def __init__(self, times: int) -> None:
        self.left = times
        self.waits = 0

    def wait(self, timeout: float | None = None) -> bool:
        self.waits += 1
        if self.left:
            self.left -= 1
            raise KeyboardInterrupt
        return True


def jobs_with(running: bool) -> Jobs:
    jobs = Jobs()
    if running:
        holding = threading.Event()
        jobs.start("index", lambda events: holding.wait(2))
    return jobs


def test_ctrl_c_with_no_job_running_stops_at_once():
    told: list[str] = []
    quitting = Interrupted(times=1)

    _wait_for_quit(quitting, jobs_with(running=False), told.append)

    assert quitting.waits == 1
    assert told == []


def test_ctrl_c_with_a_job_running_says_so_and_waits_for_a_second():
    """Quit refuses while a job runs, because the job is a daemon thread
    that may be inside the corpus lock; Ctrl-C ended it wherever it was."""
    told: list[str] = []
    quitting = Interrupted(times=2)

    # Caught here, because an interrupt escaping a test stops pytest's
    # whole run rather than failing the test, and the run then reads as
    # passing. `run` returns cleanly on the second, as on the first
    # with no job.
    try:
        _wait_for_quit(quitting, jobs_with(running=True), told.append)
    except KeyboardInterrupt:
        pytest.fail("the second Ctrl-C escaped instead of ending the wait")

    assert told == ["index"]
    assert quitting.waits == 2, "the second Ctrl-C stops it"


def test_after_the_warning_a_quit_from_the_page_still_stops_it():
    told: list[str] = []
    quitting = Interrupted(times=1)

    _wait_for_quit(quitting, jobs_with(running=True), told.append)

    assert told == ["index"]
    assert quitting.waits == 2


def test_the_command_line_words_the_warning():
    said = still_running_on_interrupt("index")

    assert "index" in said and "Ctrl-C" in said
