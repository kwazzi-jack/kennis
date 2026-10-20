"""The command line's output, byte for byte, as it was before milestone 14.

Milestone 14 moves every corpus command's work into a service and leaves the
command line as its client. What that must not change is what a person sees,
so this runs one fixed sequence of commands - every command group, the
refusals as well as the successes - and compares each command's exit code,
standard output and standard error with the files under `tests/baseline/`,
captured at `83901fc` before anything moved (14a).

A difference is either a regression or a change somebody meant, and the
second is made by regenerating the files and reading the diff:

    KENNIS_REGENERATE_BASELINE=1 uv run pytest tests/test_cli_baseline.py

What varies between runs is pinned, and what cannot be is replaced by a
placeholder, by `tests/pinned.py`, which `test_mcp_baseline.py` shares.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from pinned import BASELINE, compared_with_baseline, normalised, pin

PASSWORD = "a long enough password"


@dataclass(frozen=True)
class Step:
    """One command: its arguments, what is typed at it, and where it runs.

    An argument may be a function of the scratch folder, for the few that
    can only be known once earlier steps have run - a commit to return to.
    """

    name: str
    arguments: tuple[str | Callable[[Path], str], ...]
    typed: str | None = None
    folder: str = "."


def commit_before(count: int) -> Callable[[Path], str]:
    def resolved(scratch: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", f"HEAD~{count}"],
            cwd=scratch / "corpus",
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        ).stdout.strip()[:8]

    return resolved


def step(
    name: str,
    *arguments: str | Callable[[Path], str],
    typed: str | None = None,
    folder: str = ".",
) -> Step:
    return Step(name=name, arguments=arguments, typed=typed, folder=folder)


SCENARIO: tuple[Step, ...] = (
    step("search-without-corpus", "search", "anything"),
    step("corpus-init", "corpus", "init"),
    step("corpus-init-again", "corpus", "init"),
    step("corpus-status-empty", "corpus", "status"),
    step("corpus-list-empty", "corpus", "list"),
    step(
        "corpus-add-notes",
        "corpus",
        "add",
        "-n",
        "sources/calibration.md",
        "sources/imaging.md",
    ),
    step(
        "corpus-add-grouped",
        "corpus",
        "add",
        "-n",
        "--group",
        "topics/radio",
        "sources/beams.md",
    ),
    step("corpus-add-duplicate", "corpus", "add", "-n", "sources/imaging.md"),
    step("corpus-add-missing", "corpus", "add", "-n", "sources/absent.md"),
    step(
        "corpus-add-docs",
        "corpus",
        "add",
        "-d",
        "--project",
        "tool",
        "--version",
        "1.0",
        "sources/page.md",
    ),
    step("corpus-list", "corpus", "list"),
    step("corpus-tree", "corpus", "tree"),
    step("corpus-status-unindexed", "corpus", "status"),
    step("search-unindexed", "search", "calibration"),
    step("corpus-index", "corpus", "index"),
    step("corpus-index-quiet", "-q", "corpus", "index"),
    step("corpus-status-indexed", "corpus", "status"),
    step("search", "search", "calibration"),
    step(
        "search-notes-bm25",
        "search",
        "--collection",
        "notes",
        "--mode",
        "bm25",
        "phase",
    ),
    step("search-group", "search", "--group", "topics/*", "beam"),
    step(
        "search-docs-version",
        "search",
        "--collection",
        "docs",
        "--version",
        "all",
        "tool",
    ),
    step("search-nothing", "search", "zzzzqqqq"),
    step("read", "read", "calibration"),
    step("read-chunks", "read", "calibration", "--chunks", "0:2"),
    step("read-missing", "read", "no-such-document"),
    step("remember", "remember", "Gain solutions drift with temperature."),
    step(
        "remember-titled",
        "remember",
        "--title",
        "Flagging",
        "--group",
        "topics",
        "RFI is flagged first.",
    ),
    step("corpus-move", "corpus", "move", "imaging", "--group", "topics/radio"),
    step("corpus-remove-asked-no", "corpus", "remove", "beams", typed="n\n"),
    step("corpus-remove", "corpus", "remove", "beams", "-y"),
    step("corpus-history", "corpus", "history"),
    step(
        "corpus-restore",
        "corpus",
        "restore",
        "doc0000003",
        "--commit",
        commit_before(1),
    ),
    step("corpus-return-asked-no", "corpus", "return", commit_before(3), typed="n\n"),
    step("corpus-return", "corpus", "return", commit_before(3), "-y"),
    step(
        "corpus-history-notes",
        "corpus",
        "history",
        "--collection",
        "notes",
        "--limit",
        "5",
    ),
    step("corpus-version", "corpus", "version"),
    step("corpus-version-choose", "corpus", "version", "tool", "1.0"),
    step(
        "pack-init",
        "pack",
        "init",
        "--id",
        "demo",
        "--name",
        "A demo",
        folder="scaffold",
    ),
    step("pack-update", "pack", "update", "provider.ken.yml", folder="provider"),
    step("pack-validate", "pack", "validate", "provider.ken.yml", folder="provider"),
    step("pack-add", "pack", "add", "provider/provider.ken.yml"),
    step("pack-list", "pack", "list"),
    step("pack-list-json", "pack", "list", "--json"),
    step("pack-status", "pack", "status"),
    step("corpus-sync", "corpus", "sync"),
    step("corpus-sync-again", "corpus", "sync"),
    step("corpus-claim", "corpus", "claim", "convention"),
    step("corpus-disown", "corpus", "disown", "convention"),
    step("context-status-outside", "context", "status", folder="project"),
    step("context-init", "context", "init", folder="project"),
    step("context-status", "context", "status", folder="project"),
    step("context-sync", "context", "sync", folder="project"),
    step(
        "remember-context",
        "remember",
        "--context",
        "This project uses CASA.",
        folder="project",
    ),
    step("context-index", "context", "index", folder="project"),
    step(
        "search-context", "search", "--collection", "context", "CASA", folder="project"
    ),
    step("search-everywhere", "search", "calibration", folder="project"),
    step("context-reset", "context", "reset", typed="y\n", folder="project"),
    step("pack-remove", "pack", "remove", "provider"),
    step("backup-check-unset", "backup", "check"),
    step(
        "backup-create",
        "backup",
        "create",
        "--to",
        "backups",
        typed=f"{PASSWORD}\n{PASSWORD}\n",
    ),
    step("backup-check", "backup", "check", "--to", "backups"),
    step(
        "backup-restore-over-corpus",
        "backup",
        "restore",
        "backups/kennis-corpus.7z",
        typed=f"{PASSWORD}\n",
    ),
    step(
        "backup-restore",
        "backup",
        "restore",
        "backups/kennis-corpus.7z",
        "--to",
        "restored",
        typed=f"{PASSWORD}\n",
    ),
    step("config-path", "config", "path"),
    step(
        "corpus-index-final",
        "--no-progress",
        "corpus",
        "index",
        "--collection",
        "notes",
    ),
)


def ran(runner: CliRunner, scratch: Path, one: Step) -> str:
    arguments = [
        argument(scratch) if callable(argument) else argument
        for argument in one.arguments
    ]
    os.chdir(scratch / one.folder)
    result = runner.invoke(main, arguments, input=one.typed)
    shown = " ".join(arguments)
    return normalised(
        f"$ kennis {shown}\n"
        f"--- exit {result.exit_code}\n"
        f"--- stdout\n{result.stdout}"
        f"--- stderr\n{result.stderr}",
        scratch,
    )


def test_every_step_has_a_distinct_name():
    names = [one.name for one in SCENARIO]
    assert len(names) == len(set(names))


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return pin(tmp_path, monkeypatch)


def test_the_command_line_says_what_it_said_before_the_service(pinned: Path):
    runner = CliRunner()
    produced = {
        f"{position:02d}-{one.name}.txt": ran(runner, pinned, one)
        for position, one in enumerate(SCENARIO, start=1)
    }
    compared_with_baseline(produced, BASELINE / "cli")
