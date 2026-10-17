"""One window process at a time (Brian, 2026-10-17).

"have a single gui instance running in one window and have them pick one
they want to use, and then shut the other one down." A running `kennis gui`
holds a lock in the state directory and records where it is; a second one
is told, and opens the first, replaces it, or stops.
"""

from __future__ import annotations

import http.server
import os
import socket
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis import __version__
from kennis.cli.__main__ import main
from kennis.gui import instance
from kennis.gui.instance import (
    AlreadyOpen,
    WindowBusy,
    WindowUnreachable,
    ask_to_quit,
    open_window,
    this_window,
)
from kennis.render import words
from platforms import needs_file_modes

ADDRESS = "http://127.0.0.1:5999/?token=a-test-token"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def test_no_window_is_open_at_first():
    assert open_window() is None


def test_a_window_records_where_it_is_and_removes_the_record_when_it_stops():
    with this_window() as record:
        record(ADDRESS)
        window = open_window()

        assert window is not None
        assert window.address == ADDRESS
        assert window.pid == os.getpid()
        assert window.version == __version__

    # The file first: `open_window` removes a record nobody holds, so
    # asking it first would clean up after a window that did not.
    assert not instance.record_path().exists()
    assert open_window() is None


def test_a_second_window_is_refused_and_told_where_the_first_is():
    with this_window() as record:
        record(ADDRESS)
        with pytest.raises(AlreadyOpen) as refused, this_window():
            pass

    assert refused.value.window is not None
    assert refused.value.window.address == ADDRESS
    assert refused.value.resolution == "kennis gui --replace"


def test_a_record_nobody_holds_is_a_leftover_and_is_removed():
    """A window that crashed released its lock with the process, and left
    its record behind."""
    with this_window() as record:
        record(ADDRESS)
        left = instance.record_path().read_bytes()
    instance.record_path().write_bytes(left)

    assert open_window() is None
    assert not instance.record_path().exists()


@needs_file_modes
def test_the_record_is_readable_by_this_account_alone():
    """It carries the token. The token keeps out other accounts and pages
    served from other ports; neither can read a 0600 file."""
    with this_window() as record:
        record(ADDRESS)
        mode = stat.S_IMODE(instance.record_path().stat().st_mode)

    assert mode == 0o600


# ---------------------------------------------------------------------------
# Asking the open window to stop
# ---------------------------------------------------------------------------


def a_real_window(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Thread, str]:
    import kennis.gui.serve as serving

    monkeypatch.setattr(serving.webbrowser, "open", lambda url: True)
    ready = threading.Event()
    given: list[str] = []

    def note(url: str) -> None:
        given.append(url)
        ready.set()

    runner = threading.Thread(target=serving.run, args=(note,), daemon=True)
    runner.start()
    assert ready.wait(10)
    return runner, given[0]


def test_serving_records_the_window_it_serves(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    runner, address = a_real_window(monkeypatch)
    window = open_window()

    assert window is not None and window.address == address
    ask_to_quit(window)
    runner.join(10)
    assert not runner.is_alive()
    assert open_window() is None


def test_serving_refuses_while_another_window_is_open(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    import kennis.gui.serve as serving

    # Without the refusal it would serve until Quit: the test must fail,
    # not hang.
    monkeypatch.setattr(serving, "_wait_for_quit", lambda *_: None)
    announced: list[str] = []
    with this_window() as record:
        record(ADDRESS)
        with pytest.raises(AlreadyOpen):
            serving.run(announced.append, open_browser=False)

    assert announced == []


@pytest.fixture
def answering() -> Iterator[list[int]]:
    """A server on loopback that answers every POST with the status given."""
    status = [409]

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(status[0])
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    status.append(server.server_address[1])
    yield status
    server.shutdown()
    server.server_close()


def test_a_window_running_a_job_says_it_is_busy(answering: list[int]):
    with this_window() as record:
        record(f"http://127.0.0.1:{answering[1]}/?token=t")
        window = open_window()
        assert window is not None

        with pytest.raises(WindowBusy):
            ask_to_quit(window)


def test_a_window_that_does_not_answer_is_named_by_its_process():
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
    with this_window() as record:
        record(f"http://127.0.0.1:{port}/?token=t")
        window = open_window()
        assert window is not None

        with pytest.raises(WindowUnreachable) as refused:
            ask_to_quit(window)

    assert str(os.getpid()) in str(refused.value)


# ---------------------------------------------------------------------------
# `kennis gui` when a window is open
# ---------------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What `kennis gui` started or opened instead of really serving."""
    import kennis.gui.serve as serving

    calls: list[str] = []
    monkeypatch.setattr(serving, "run", lambda *args, **kwargs: calls.append("run"))
    monkeypatch.setattr(
        serving, "open_quietly", lambda url: calls.append(f"open {url}")
    )
    return calls


def test_with_a_window_open_kennis_gui_opens_it(corpus: Path, served: list[str]):
    with this_window() as record:
        record(ADDRESS)
        result = CliRunner().invoke(main, ["gui"])

    assert result.exit_code == 0, result.output
    assert served == [f"open {ADDRESS}"]
    assert words.window_already_open("", "").split(",")[0] in result.output


def test_with_no_browser_it_prints_the_open_windows_address(
    corpus: Path, served: list[str]
):
    with this_window() as record:
        record(ADDRESS)
        result = CliRunner().invoke(main, ["gui", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert served == []
    assert ADDRESS in result.output


def test_replace_stops_the_open_window_and_then_serves(
    corpus: Path, served: list[str], monkeypatch: pytest.MonkeyPatch
):
    stopped: list[str] = []
    monkeypatch.setattr(
        instance, "ask_to_quit", lambda window: stopped.append(window.address)
    )
    with this_window() as record:
        record(ADDRESS)
        result = CliRunner().invoke(main, ["gui", "--replace"])

    assert result.exit_code == 0, result.output
    assert stopped == [ADDRESS]
    assert served == ["run"]


def test_a_busy_window_is_not_replaced(
    corpus: Path, served: list[str], monkeypatch: pytest.MonkeyPatch
):
    def busy(window: object) -> None:
        raise WindowBusy()

    monkeypatch.setattr(instance, "ask_to_quit", busy)
    with this_window() as record:
        record(ADDRESS)
        result = CliRunner().invoke(main, ["gui", "--replace"])

    assert result.exit_code != 0
    assert served == []
    assert WindowBusy.default_message in result.output


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("replace\n", ["run"]), ("cancel\n", []), ("\n", [f"open {ADDRESS}"])],
)
def test_a_terminal_is_asked_to_pick_one(
    corpus: Path,
    served: list[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
    expected: list[str],
):
    from kennis.cli.commands import gui

    monkeypatch.setattr(gui, "_asked_in_a_terminal", lambda: True)
    monkeypatch.setattr(instance, "ask_to_quit", lambda window: None)
    with this_window() as record:
        record(ADDRESS)
        result = CliRunner().invoke(main, ["gui"], input=typed)

    assert result.exit_code == 0, result.output
    assert served == expected
    assert words.OPEN_OR_REPLACE in result.output
