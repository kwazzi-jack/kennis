"""Time the commands milestone 14 is meant to speed up, and measure memory.

Run with `uv run python scripts/measure_service_baseline.py [folder]`. It
builds a scratch corpus in `folder` (a temporary directory without one) from
the markdown pages of kennis's own `docs/`, indexes it with the default
embedding backend, and prints the median of several runs of each command.
The configuration, corpus, state and log directories all point inside the
folder, so no corpus but the scratch one is read or written.

The embedding model must already be in kennis's model cache, or the first
index downloads it - which is a network fetch and would be timed.

The same script is run before milestone 14 (the baseline in `design/plan.md`)
and after each unit that moves work into the service, so the two sets of
numbers are measured by one instrument.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
RUNS = 7
MCP_RUNS = 5
QUERY = "backup password"
JsonObject = dict[str, object]


def kennis_command() -> list[str]:
    return [sys.executable, "-m", "kennis.cli.__main__"]


def environment(folder: Path) -> dict[str, str]:
    variables = dict(os.environ)
    variables.update(
        KENNIS_CONFIG_DIR=str(folder / "config"),
        KENNIS_CORPUS_ROOT=str(folder / "corpus"),
        KENNIS_STATE_DIR=str(folder / "state"),
        KENNIS_LOG_DIR=str(folder / "log"),
        KENNIS_EMBEDDING_BACKEND="fastembed",
    )
    return variables


def run_kennis(folder: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*kennis_command(), *arguments],
        env=environment(folder),
        cwd=folder,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )


def build_corpus(folder: Path) -> None:
    for part in ("config", "corpus", "state", "log"):
        shutil.rmtree(folder / part, ignore_errors=True)
    steps: list[list[str]] = [
        ["corpus", "init"],
        ["corpus", "add", "-n", *map(str, sorted((REPOSITORY / "docs").rglob("*.md")))],
        ["corpus", "index"],
    ]
    for step in steps:
        result = run_kennis(folder, *step)
        if result.returncode != 0:
            raise SystemExit(f"kennis {step[0]} {step[1]} failed:\n{result.stderr}")


def median_seconds(action: Callable[[], None], runs: int) -> float:
    action()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        action()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def timed_command(folder: Path, *arguments: str) -> float:
    def action() -> None:
        result = run_kennis(folder, *arguments)
        if result.returncode != 0:
            raise SystemExit(f"kennis {' '.join(arguments)} failed:\n{result.stderr}")

    return median_seconds(action, RUNS)


def resident_mebibytes(process_id: int) -> float | None:
    """`VmRSS` from `/proc`, which exists on Linux only."""
    status = Path(f"/proc/{process_id}/status")
    if not status.exists():
        return None
    for line in status.read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return None


def mcp_first_search(folder: Path) -> tuple[float, float | None]:
    """Start `kennis serve`, initialise it, call `search_notes` once; the time
    from starting the process to the answer, and its memory after."""
    start = time.perf_counter()
    server = subprocess.Popen(
        [*kennis_command(), "serve"],
        env=environment(folder),
        cwd=folder,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert server.stdin is not None and server.stdout is not None
    sending, receiving = server.stdin, server.stdout

    def send(message: JsonObject) -> None:
        sending.write(json.dumps(message) + "\n")
        sending.flush()

    def answer(wanted: int) -> JsonObject:
        while True:
            message: JsonObject = json.loads(receiving.readline())
            if message.get("id") == wanted:
                return message

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "measure", "version": "0"},
            },
        }
    )
    answer(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_notes", "arguments": {"question": QUERY}},
        }
    )
    reply = answer(2)
    elapsed = time.perf_counter() - start
    result = reply.get("result")
    if "error" in reply or not isinstance(result, dict) or result.get("isError"):
        raise SystemExit(f"the MCP search failed: {reply}")
    memory = resident_mebibytes(server.pid)
    server.terminate()
    server.wait(timeout=30)
    return elapsed, memory


def main() -> None:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1]).resolve()
        folder.mkdir(parents=True, exist_ok=True)
    else:
        folder = Path(tempfile.mkdtemp(prefix="kennis-measure-"))
    build_corpus(folder)
    rows = {
        "kennis --version": timed_command(folder, "--version"),
        "kennis search (hybrid)": timed_command(folder, "search", QUERY),
        "kennis search --mode bm25": timed_command(
            folder, "search", "--mode", "bm25", QUERY
        ),
        "kennis read": timed_command(folder, "read", "privacy"),
        "kennis read --chunks 0:2": timed_command(
            folder, "read", "privacy", "--chunks", "0:2"
        ),
        "kennis corpus status": timed_command(folder, "corpus", "status"),
    }
    for name, seconds in rows.items():
        print(f"{name:32s} {seconds:6.2f} s")
    starts = [mcp_first_search(folder) for _ in range(MCP_RUNS)]
    print(
        f"{'MCP start to first search':32s} "
        f"{statistics.median(seconds for seconds, _ in starts):6.2f} s"
    )
    memories = [memory for _, memory in starts if memory is not None]
    if memories:
        print(
            f"{'MCP resident after a search':32s} "
            f"{statistics.median(memories):6.0f} MiB"
        )


if __name__ == "__main__":
    main()
