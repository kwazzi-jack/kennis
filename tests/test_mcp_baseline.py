"""What an agent is told, byte for byte, as it was before milestone 14.

The MCP twin of `test_cli_baseline.py`. 14d makes the MCP server a client of
the service; what an agent sees must not change with it. So this connects to
the server the way an agent does - fastmcp's in-memory client, through the
protocol, not by calling the tool functions - and compares with
`tests/baseline/mcp/`: the instructions block, every tool's name,
description and input schema, and the answer to each call in a fixed
sequence, refusals included. Captured at `83901fc`.

    KENNIS_REGENERATE_BASELINE=1 uv run pytest tests/test_mcp_baseline.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastmcp import Client

from kennis.cli.__main__ import main
from kennis.mcp.server import build_server
from pinned import BASELINE, compared_with_baseline, normalised, pin

type Arguments = dict[str, object]

# Each call: a name for its file, the tool, its arguments, and the folder it
# is made from (`project` holds a context bundle).
CALLS: tuple[tuple[str, str, Arguments, str], ...] = (
    ("list-corpus", "list_corpus", {}, "."),
    (
        "list-corpus-notes-documents",
        "list_corpus",
        {"collection": "notes", "detail": "documents"},
        ".",
    ),
    ("list-corpus-unknown", "list_corpus", {"collection": "elsewhere"}, "."),
    ("search-notes", "search_notes", {"question": "calibration"}, "."),
    ("search-notes-top-one", "search_notes", {"question": "phase", "top_k": 1}, "."),
    ("search-literature-empty", "search_literature", {"question": "calibration"}, "."),
    ("search-docs", "search_docs", {"question": "tool"}, "."),
    (
        "search-docs-version",
        "search_docs",
        {"question": "tool", "version": ["all"]},
        ".",
    ),
    ("search-context-outside", "search_context", {"question": "CASA"}, "."),
    ("search-context", "search_context", {"question": "CASA"}, "project"),
    (
        "read-notes",
        "read_notes",
        {
            "requests": [
                {"document_id": "doc0000001"},
                {"document_id": "doc0000001", "chunk_index": 2, "before": 0},
                {"document_id": "no-such-document"},
                {"document_id": "doc0000001", "chunk_index": -1},
            ]
        },
        ".",
    ),
    (
        "read-docs-wrong-collection",
        "read_docs",
        {"requests": [{"document_id": "doc0000001"}]},
        ".",
    ),
    ("remember", "remember", {"text": "Gain solutions drift with temperature."}, "."),
    (
        "remember-again",
        "remember",
        {"text": "Gain solutions drift with temperature."},
        ".",
    ),
    (
        "remember-titled",
        "remember",
        {"text": "RFI is flagged first.", "title": "Flagging", "group": "topics"},
        ".",
    ),
    ("remember-bad-group", "remember", {"text": "Escape.", "group": "../outside"}, "."),
    (
        "remember-context-outside",
        "remember",
        {"text": "A project note.", "to_context": True},
        ".",
    ),
    (
        "remember-context",
        "remember",
        {"text": "A project note.", "to_context": True},
        "project",
    ),
)

# Building the corpus the calls are made against, by the command line.
SETUP: tuple[tuple[str, ...], ...] = (
    ("corpus", "init"),
    ("corpus", "add", "-n", "sources/calibration.md", "sources/imaging.md"),
    ("corpus", "add", "-d", "--project", "tool", "--version", "1.0", "sources/page.md"),
    ("pack", "install", "provider/provider.ken.yml"),
    ("corpus", "sync"),
    ("corpus", "index"),
)


def built(scratch: Path) -> None:
    runner = CliRunner()
    os.chdir(scratch)
    for arguments in SETUP:
        result = runner.invoke(main, list(arguments))
        assert result.exit_code == 0, (arguments, result.output)
    os.chdir(scratch / "project")
    for arguments in (
        ("context", "init"),
        ("remember", "--context", "CASA is used here."),
        ("context", "index"),
    ):
        result = runner.invoke(main, list(arguments))
        assert result.exit_code == 0, (arguments, result.output)
    os.chdir(scratch)


def answer_text(result: object) -> str:
    """The parts of a tool's answer an agent reads: whether it is an error,
    and each text block."""
    is_error = getattr(result, "is_error", None)
    blocks = getattr(result, "content", [])
    texts = [getattr(block, "text", repr(block)) for block in blocks]
    return f"--- error {is_error}\n" + "\n--- next block\n".join(texts) + "\n"


async def conversation(scratch: Path) -> dict[str, str]:
    produced: dict[str, str] = {}
    async with Client(build_server()) as client:
        produced["00-instructions.txt"] = (client.instructions or "") + "\n"
        tools = await client.list_tools_mcp()
        produced["00-tools.txt"] = (
            json.dumps(
                [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input": tool.input_schema,
                        "output": tool.output_schema,
                    }
                    for tool in tools.tools
                ],
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        for position, (name, tool, arguments, folder) in enumerate(CALLS, start=1):
            os.chdir(scratch / folder)
            result = await client.call_tool_mcp(tool, arguments)
            shown = json.dumps(arguments, sort_keys=True)
            produced[f"{position:02d}-{name}.txt"] = (
                f"$ {tool} {shown}\n" + answer_text(result)
            )
    return {key: normalised(text, scratch) for key, text in produced.items()}


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return pin(tmp_path, monkeypatch)


def test_every_call_has_a_distinct_name():
    names = [name for name, *_ in CALLS]
    assert len(names) == len(set(names))


def test_an_agent_is_told_what_it_was_told_before_the_service(pinned: Path):
    built(pinned)
    produced = asyncio.run(conversation(pinned))
    compared_with_baseline(produced, BASELINE / "mcp")
