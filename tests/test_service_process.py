"""The service as a real process: started, found, replaced and stopped (14b).

Marked `service` and deselected by default, because each test starts a
Python process that imports the engine (about a second here). Run with
`uv run pytest -m service`; CI runs them on every system (14f).

The child inherits the test's environment, so every redirection the
autouse fixtures make - the state directory, the configuration, the
corpus - reaches it, and a test's service never meets Brian's.

A process's end is read from its lock rather than its process id: the
kernel releases the lock when the process exits, whereas the id of a child
nobody has reaped yet still answers a signal.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.client import process as client
from kennis.client.process import (
    ensure_service,
    hello,
    start_detached,
    stop_service,
)
from kennis.engine.errors import ServiceUnavailable
from kennis.engine.locking import corpus_lock
from kennis.protocol.record import find_service, is_held, read_record, record_path

pytestmark = pytest.mark.service

PATIENCE = 30.0


def eventually(condition: Callable[[], bool], within: float = PATIENCE) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def ended(pid: int) -> None:
    """End a process as a crash would, with no chance to tidy up."""
    if sys.platform == "win32":
        # `os.kill` with any signal but the two console events calls
        # `TerminateProcess` there.
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGKILL)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    yield root
    # Whatever a test left running is ended, so no process outlives it.
    record = find_service(root)
    if record is not None:
        with contextlib.suppress(ProcessLookupError):
            ended(record.pid)
        eventually(lambda: not is_held(root))


def test_a_client_with_no_service_starts_one(corpus: Path):
    assert find_service(corpus) is None

    record = ensure_service(corpus)

    assert is_held(corpus)
    assert record.pid != os.getpid()
    answered = hello(record)
    assert answered is not None
    assert answered["corpus"] == str(corpus)


def test_a_module_in_the_corpus_root_is_not_imported_by_the_service(
    corpus: Path,
):
    """A file a person dropped in the corpus root is not imported in place
    of a library: the service runs there (#508), and `-m` would put its
    working directory first on `sys.path` without `-P`."""
    (corpus / "httpx.py").write_text(
        "raise SystemExit('the corpus root was imported from')\n", encoding="utf-8"
    )

    record = ensure_service(corpus)

    assert hello(record) is not None


def test_a_second_client_finds_the_same_service(corpus: Path):
    first = ensure_service(corpus)
    second = ensure_service(corpus)

    assert second.pid == first.pid
    assert second.token == first.token


def test_a_stopped_service_lets_go_and_leaves_no_record(corpus: Path):
    record = ensure_service(corpus)

    stop_service(corpus, record)

    assert not is_held(corpus)
    assert eventually(lambda: not record_path(corpus).exists())


def test_a_crashed_service_is_noticed_and_replaced(corpus: Path):
    """Its record survives it; its lock does not, and the lock decides."""
    crashed = ensure_service(corpus)
    ended(crashed.pid)
    assert eventually(lambda: not is_held(corpus))
    assert read_record(corpus) == crashed

    replacement = ensure_service(corpus)

    assert replacement.pid != crashed.pid
    assert hello(replacement) is not None


def test_a_quiet_service_leaves_by_itself(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """Shortened by the setting, never by sleeping thirty minutes."""
    monkeypatch.setenv("KENNIS_SERVICE_IDLE_MINUTES", "0.02")
    ensure_service(corpus)

    assert eventually(lambda: not is_held(corpus))
    assert not record_path(corpus).exists()


def test_a_service_nobody_speaks_to_still_leaves(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """Every request re-arms the timer, so this is the case where only the
    service's own start arms it: started, and never asked anything."""
    monkeypatch.setenv("KENNIS_SERVICE_IDLE_MINUTES", "0.02")

    assert start_detached(corpus) == 0
    assert is_held(corpus)

    assert eventually(lambda: not is_held(corpus))


def test_a_service_of_another_version_is_replaced_when_idle(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """The client is made to be of another version; the service, started
    from the same installation, answers its own."""
    older = ensure_service(corpus)
    monkeypatch.setattr(client, "__version__", "0.0.0+another")

    newer = ensure_service(corpus)

    assert newer.pid != older.pid
    assert hello(newer) is not None


def test_the_window_s_quit_ends_the_service(corpus: Path):
    record = ensure_service(corpus)

    answer = httpx.post(f"{record.address}quit", params={"token": record.token})

    assert answer.status_code == 200
    assert eventually(lambda: not is_held(corpus))


@pytest.mark.skipif(sys.platform == "win32", reason="Windows sends no SIGTERM")
def test_a_terminate_signal_stops_an_idle_service(corpus: Path):
    record = ensure_service(corpus)

    os.kill(record.pid, signal.SIGTERM)

    assert eventually(lambda: not is_held(corpus))
    assert eventually(lambda: not record_path(corpus).exists())


def test_a_service_started_from_a_program_leaves_its_stdout_alone(corpus: Path):
    """Under `kennis serve` a client's stdout is the MCP wire (#291).

    The parent prints one line and exits; reading its stdout to the end
    returns only that line, and returns at once - a service that had
    inherited the stream would hold it open for as long as it runs.
    """
    program = (
        "from pathlib import Path\n"
        "from kennis.client.process import ensure_service\n"
        f"ensure_service(Path({str(corpus)!r}))\n"
        "print('the parent')\n"
    )
    began = time.monotonic()
    finished = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=PATIENCE * 2,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout == "the parent\n"
    assert time.monotonic() - began < PATIENCE
    assert is_held(corpus)


def test_a_client_is_told_when_the_folder_is_no_corpus(tmp_path: Path):
    """Reported by the launcher's status at once, with the log's place,
    rather than after the thirty seconds a start may take."""
    began = time.monotonic()

    with pytest.raises(ServiceUnavailable, match="status 2"):
        ensure_service(tmp_path / "nothing")

    assert time.monotonic() - began < PATIENCE / 3
    assert not is_held(tmp_path / "nothing")


def test_a_real_command_waits_while_the_corpus_is_held_and_then_writes(
    corpus: Path, tmp_path: Path
):
    """The whole path, through the installed `kennis` and the service it
    starts: a write that finds the corpus held waits for it (14b), rather
    than being refused, and then does its work."""
    note = tmp_path / "a note.md"
    note.write_text("# A note\n\nBody.\n", encoding="utf-8")
    holding = threading.Event()

    def hold() -> None:
        with corpus_lock(corpus):
            holding.set()
            threading.Event().wait(1.0)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert holding.wait(PATIENCE)
    began = time.monotonic()
    completed = subprocess.run(
        [str(Path(sys.executable).parent / "kennis"), "corpus", "add", "-n", str(note)],
        env={**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)},
        capture_output=True,
        text=True,
        timeout=PATIENCE * 2,
        stdin=subprocess.DEVNULL,
    )
    holder.join(PATIENCE)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert time.monotonic() - began >= 0.5
    assert len(sorted((corpus / "notes").rglob("*.md"))) == 1
