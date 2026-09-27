"""The server, over a real pipe.

**One invariant here outranks every feature in the milestone.** Under
`kennis serve`, stdout *is* the JSON-RPC wire: a byte on it that is not
protocol corrupts the session. boepie lost one to 567 bytes of INFO from
a library's module-level `Console(file=sys.stdout)` and got back
`Invalid JSON: trailing characters at line 1 column 5`. Design section
14 names the test and this is it.

**It has to be a subprocess.** In-process capture proves nothing about a
library that writes at import time, which is the failure being guarded,
and nothing about a C extension writing to file descriptor 1 behind
Python's `sys.stdout`. So: spawn the real command, speak the handshake,
call a real tool, and hold every byte that came back to being protocol.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main

# Slow because each test spawns a real interpreter and imports fastmcp.
# Marked rather than trimmed: the subprocess is the whole point, and a
# faster version of this test would not test the thing.
pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    return tmp_path


@pytest.fixture
def corpus(isolated: Path) -> Path:
    result = CliRunner().invoke(main, ["corpus", "init"])
    assert result.exit_code == 0, result.output
    return isolated / "corpus"


_TIMEOUT_SECONDS = 60
# Long enough for a synchronous tool to be dispatched and answered
# before the next message arrives. See `a_session`.
_SETTLE_SECONDS = 0.6


def request(identifier: int, method: str, params: dict[str, object]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
    )


def notification(method: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": {}})


@dataclass(frozen=True, slots=True)
class Session:
    """What one conversation produced, on both streams."""

    stdout: str
    stderr: str


def a_session(corpus_root: Path) -> Session:
    """Initialise, list the tools, call one, and close the pipe.

    **stdin is held open and the replies are read as they arrive**, which
    is not incidental. Writing the whole conversation and closing stdin
    immediately makes the server exit before it has dispatched a
    *synchronous* tool to its worker thread: the handshake is answered
    and the tool call never is. That looked like a broken tool and was a
    broken test.
    """
    environment = dict(os.environ)
    environment["KENNIS_CORPUS_ROOT"] = str(corpus_root)
    # Unbuffered, and this is what makes the guard real rather than
    # lucky. stdout to a pipe is block-buffered, so a stray `print` in a
    # short session sits in an 8 KiB buffer and is discarded when the
    # process exits - the offending line never appears and the test
    # passes. I found this by injecting one and watching it be missed.
    # Unbuffered, every write lands immediately, so the test catches an
    # offender whether or not it flushes. In a real session the buffer
    # fills and flushes eventually, so the risk is the same; only the
    # test's ability to see it differed.
    environment["PYTHONUNBUFFERED"] = "1"
    received: list[str] = []
    # A context manager, so the three pipes are closed. Without it the
    # suite's `filterwarnings = ["error"]` turns the leaked readers into
    # a ResourceWarning and fails the test for a reason that has nothing
    # to do with the server.
    with subprocess.Popen(
        [sys.executable, "-m", "kennis.cli", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=environment,
    ) as server:

        def read_stdout() -> None:
            assert server.stdout is not None
            received.extend(line.rstrip("\n") for line in server.stdout)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        assert server.stdin is not None
        for line in (
            request(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "kennis-tests", "version": "0"},
                },
            ),
            notification("notifications/initialized"),
            request(2, "tools/list", {}),
            request(3, "tools/call", {"name": "list_corpus", "arguments": {}}),
        ):
            server.stdin.write(line + "\n")
            server.stdin.flush()
            time.sleep(_SETTLE_SECONDS)

        server.stdin.close()
        server.wait(timeout=_TIMEOUT_SECONDS)
        reader.join(timeout=_TIMEOUT_SECONDS)
        assert server.stderr is not None
        complaints = server.stderr.read()
    return Session(stdout="\n".join(received), stderr=complaints)


def messages_in(stdout: str) -> list[dict[str, object]]:
    """Every line of stdout, parsed. A line that is not JSON fails here,
    which is the point: this is the assertion, not a helper for it."""
    parsed: list[dict[str, object]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise AssertionError(
                f"stdout carried a line that is not JSON-RPC: {line!r} ({error})"
            ) from error
    return parsed


def test_serve_writes_nothing_to_stdout_but_protocol(corpus: Path):
    """The invariant. Every byte on stdout parses as a JSON-RPC message.

    Not "stdout is empty" - the protocol lives there - but "stdout is
    *only* the protocol", which is the property a stray print breaks.
    """
    finished = a_session(corpus)

    assert messages_in(finished.stdout), finished.stderr


def test_the_tool_call_succeeds_over_the_wire(corpus: Path):
    """The handshake is real and the tool actually ran, so the test above
    is asserting about a session that did something."""
    finished = a_session(corpus)

    answers = {
        message.get("id"): message
        for message in messages_in(finished.stdout)
        if "id" in message
    }
    assert 3 in answers, f"no answer to the tool call: {answers}"
    assert "error" not in answers[3], answers[3]


def test_the_tool_is_advertised(corpus: Path):
    finished = a_session(corpus)

    listed = next(
        message for message in messages_in(finished.stdout) if message.get("id") == 2
    )
    result = listed["result"]
    assert isinstance(result, dict)
    tools = result["tools"]
    assert isinstance(tools, list)
    # Every tool, not just the first one written. A tool that exists and
    # is never registered is invisible to an agent, and nothing else in
    # the suite would notice: the in-process tests call the functions
    # directly.
    assert {tool["name"] for tool in tools} == {
        "list_corpus",
        "search_context",
        "search_docs",
        "search_literature",
        "search_notes",
    }


def test_the_server_describes_itself_over_the_wire(corpus: Path):
    """The instructions block reaches the client, which is the only place
    it matters: a block that is correct and never sent is not correct."""
    finished = a_session(corpus)

    initialised = next(
        message for message in messages_in(finished.stdout) if message.get("id") == 1
    )
    result = initialised["result"]
    assert isinstance(result, dict)
    assert "kennis holds durable knowledge" in str(result.get("instructions"))
