"""Every MCP tool call is logged, answered or refused.

Brian, 2026-11-27 (#711): kennis logged `kennis serve` starting and nothing
after it, so an agent's refused calls - #710's `query` for `question` -
could be seen only from the agent's side. One line per call now goes to
the log: the tool, its arguments as given, how long it took, and whether
it answered or was refused and why. A refusal by the schema never
reaches the tool, so the line is written around the whole call, and the
case that mattered is tested through the protocol as an agent makes it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastmcp import Client
from fastmcp.exceptions import ToolError

from kennis.cli.__main__ import main
from kennis.logs import start_logging, stop_logging
from kennis.mcp.server import build_server


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    source = tmp_path / "sources" / "calibration.md"
    source.parent.mkdir(parents=True)
    source.write_text("# calibration\n\nAntenna gains and sky models.\n")
    for arguments in (
        ["corpus", "init"],
        ["corpus", "add", "-n", str(source)],
        ["corpus", "index"],
    ):
        result = run.invoke(main, arguments)
        assert result.exit_code == 0, result.output
    return tmp_path / "corpus"


@pytest.fixture
def log(corpus: Path) -> Iterator[Path]:
    """The log as `kennis serve` has it, holding only what follows."""
    path = start_logging()
    path.write_text("", encoding="utf-8")
    yield path
    stop_logging()


def called(tool: str, arguments: dict[str, object]) -> None:
    async def calling() -> None:
        async with Client(build_server()) as client:
            await client.call_tool(tool, arguments)

    asyncio.run(calling())


def lines_about(log: Path, tool: str) -> list[str]:
    return [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if "kennis.mcp" in line and f" {tool} " in line
    ]


def test_an_answered_call_is_logged_with_its_arguments(log: Path):
    called("search", {"query": "antenna gains", "collections": ["notes"]})

    [line] = lines_about(log, "search")
    assert " INFO " in line
    assert "search query='antenna gains' collections=['notes'] answered in" in line


def test_a_call_the_schema_refused_is_logged_with_why(log: Path):
    """#710's shape: the call never reaches the tool."""
    with pytest.raises(ToolError):
        called("search", {"question": "antenna gains", "collections": ["notes"]})

    [line] = lines_about(log, "search")
    assert " WARNING " in line
    assert "search question='antenna gains' collections=['notes'] refused in" in line
    assert "query missing_argument" in line
    assert "question unexpected_keyword_argument" in line


def test_a_tool_that_raised_is_logged_with_its_message(log: Path):
    """A refusal of kennis's own, past the schema: an index the agent
    named that does not exist."""
    with pytest.raises(ToolError):
        called("search", {"query": "antenna gains", "collections": ["literature"]})

    [line] = lines_about(log, "search")
    assert " WARNING " in line
    assert "refused in" in line
    assert "NothingToIndex: the 'literature' collection has no index yet" in line


def test_a_long_argument_is_cut(log: Path):
    """`remember` carries a whole note; the log says what was asked, not
    a second copy of it."""
    text = "Gain solutions drift with temperature. " * 50

    called("remember", {"text": text})

    [line] = lines_about(log, "remember")
    assert text not in line
    assert "text='Gain solutions drift" in line
    assert len(line) < 400


def test_a_tool_that_crashed_is_an_error_with_its_traceback(log: Path):
    """A refusal is kennis working; any other exception is a defect in
    kennis, and the traceback is what finding it needs (Brian,
    2026-11-28)."""
    server = build_server()

    @server.tool
    def broken(text: str) -> str:
        """A tool with a defect in it."""
        raise RuntimeError("a defect in the tool")

    async def calling() -> None:
        async with Client(server) as client:
            await client.call_tool("broken", {"text": "x"})

    with pytest.raises(ToolError):
        asyncio.run(calling())

    [line] = lines_about(log, "broken")
    assert " ERROR " in line
    assert "broken text='x' failed in" in line
    assert "RuntimeError: a defect in the tool" in line
    written = log.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in written
    assert 'raise RuntimeError("a defect in the tool")' in written
