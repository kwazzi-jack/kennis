"""What setting kennis up needs beyond the settings walk (#682).

Beside `context.py` rather than in a front end, because the command
line's `kennis setup` and the window's wizard ask the same questions of
the machine: is the `mcp` extra installed, is Claude Code here and does it
already serve kennis, and where is this kennis. Facts and one action; the
words are each front end's.

**kennis writes no other program's configuration.** Claude Code's servers
live in `~/.claude.json` beside other servers' keys, so kennis asks Claude
Code's own command to add itself rather than editing that file; for any
other agent it hands over what to paste.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

# `claude mcp add` writes a file and returns; a minute is ample, and a hung
# one must not hold the walk for ever (every external process gets a
# timeout).
CLAUDE_TIMEOUT_SECONDS: Final = 60
# The name kennis is served under, in Claude Code and in the pasted block.
SERVER_NAME: Final = "kennis"
# What installs the extra `kennis serve` needs.
MCP_INSTALL: Final = 'uv tool install "kennis[mcp]"'


def mcp_installed() -> bool:
    """Whether `kennis serve` can run: the `mcp` extra's server library is
    importable. Looked for, not imported, which would cost a second."""
    return importlib.util.find_spec("fastmcp") is not None


def claude_on_path() -> bool:
    return shutil.which("claude") is not None


def claude_code(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Claude Code's command line, run with `arguments`."""
    executable = shutil.which("claude")
    if executable is None:
        raise FileNotFoundError("claude is not on PATH")
    return subprocess.run(
        [executable, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        timeout=CLAUDE_TIMEOUT_SECONDS,
        check=False,
    )


def this_kennis() -> Path:
    """The `kennis` executable of this installation, by its full path.

    An agent starts the server with its own PATH, which need not hold the
    tool's directory, so the path is given whole. Beside this interpreter,
    where both a `uv tool` install and a virtual environment put it; the
    symlink to the interpreter is not resolved, since the executable sits
    beside the link, not beside its target.
    """
    folder = Path(sys.executable).parent
    for name in ("kennis", "kennis.exe"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    found = shutil.which("kennis")
    if found is None:
        raise FileNotFoundError("no kennis executable beside this interpreter")
    return Path(found)


def claude_serves_kennis() -> bool:
    """Whether Claude Code already has a server named kennis, in any scope."""
    return claude_code(["mcp", "get", SERVER_NAME]).returncode == 0


def add_to_claude_code(kennis: Path) -> subprocess.CompletedProcess[str]:
    """Ask Claude Code to start `kennis serve` for every project of this
    user. The result as Claude Code answered it."""
    return claude_code(
        ["mcp", "add", "--scope", "user", SERVER_NAME, "--", str(kennis), "serve"]
    )


def server_block(kennis: Path) -> str:
    """What an agent's MCP configuration holds for kennis, to paste."""
    return json.dumps(
        {"mcpServers": {SERVER_NAME: {"command": str(kennis), "args": ["serve"]}}},
        indent=2,
    )


__all__ = [
    "CLAUDE_TIMEOUT_SECONDS",
    "MCP_INSTALL",
    "SERVER_NAME",
    "add_to_claude_code",
    "claude_code",
    "claude_on_path",
    "claude_serves_kennis",
    "mcp_installed",
    "server_block",
    "this_kennis",
]
