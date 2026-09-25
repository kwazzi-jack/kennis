"""`kennis context` at the command line.

Separate from `test_context_bundle.py`, which exercises the same behaviour
through the engine. Both exist because #88: `--quiet` crossed a milestone
with all six of its guards missing and nothing noticed for five milestones,
because no test ran a command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.context import BUNDLE_DIRNAME


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repository, because `init` finds the root by looking for
    one and a fake `.git` file would not tell us the walk works."""
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=root,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    monkeypatch.chdir(root)
    return root


def test_init_creates_the_bundle_and_says_where(workspace: Path, run: CliRunner):
    result = run.invoke(main, ["context", "init"])

    assert result.exit_code == 0, result.output
    assert (workspace / BUNDLE_DIRNAME / "bundle.json").is_file()
    assert str(workspace / BUNDLE_DIRNAME) in result.output


def test_init_from_a_subdirectory_creates_it_at_the_workspace_root(
    workspace: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The path is reported precisely because it is not where you stood."""
    deep = workspace / "src" / "engine"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)

    result = run.invoke(main, ["context", "init"])

    assert result.exit_code == 0, result.output
    assert (workspace / BUNDLE_DIRNAME).is_dir()
    assert not (deep / BUNDLE_DIRNAME).exists()


def test_here_overrides_the_walk(
    workspace: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    deep = workspace / "src" / "engine"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)

    result = run.invoke(main, ["context", "init", "--here"])

    assert result.exit_code == 0, result.output
    assert (deep / BUNDLE_DIRNAME).is_dir()
    assert not (workspace / BUNDLE_DIRNAME).exists()


def test_a_second_init_reports_the_bundle_rather_than_failing(
    workspace: Path, run: CliRunner
):
    assert run.invoke(main, ["context", "init"]).exit_code == 0

    result = run.invoke(main, ["context", "init"])

    assert result.exit_code == 0, result.output
    assert "Found" in result.output


def test_a_second_init_puts_back_a_deleted_scaffold_file(
    workspace: Path, run: CliRunner
):
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    (workspace / BUNDLE_DIRNAME / "LANDING.md").unlink()

    result = run.invoke(main, ["context", "init"])

    assert result.exit_code == 0, result.output
    assert "LANDING.md" in result.output
    assert (workspace / BUNDLE_DIRNAME / "LANDING.md").is_file()


def test_init_leaves_a_file_the_user_wrote_alone(workspace: Path, run: CliRunner):
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    mine = workspace / BUNDLE_DIRNAME / "conventions.md"
    mine.write_text("We image in 2 GHz sub-bands.\n", encoding="utf-8")

    assert run.invoke(main, ["context", "init"]).exit_code == 0

    assert mine.read_text(encoding="utf-8") == "We image in 2 GHz sub-bands.\n"


def test_quiet_prints_nothing_on_success(workspace: Path, run: CliRunner):
    """#88: a guard that is not tested is a guard that goes missing."""
    result = run.invoke(main, ["--quiet", "context", "init"])

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert (workspace / BUNDLE_DIRNAME / "bundle.json").is_file()


def test_the_printed_landing_path_exists_and_is_on_one_line(
    workspace: Path, run: CliRunner
):
    """Rule 4.4 for a path rather than a command: what is printed is real,
    and it is printed in a form that can be copied.

    Relative, because an absolute one is long enough for the prose style
    that prints it to wrap - and a path broken across two lines is not a
    path any more. Found by running the command.
    """
    result = run.invoke(main, ["context", "init"])

    assert result.exit_code == 0, result.output
    printed = [line for line in result.output.splitlines() if "LANDING.md" in line]
    assert len(printed) == 1, result.output
    relative = printed[0].split("start at ")[-1].strip()
    assert relative == f"{BUNDLE_DIRNAME}/LANDING.md"
    assert (workspace / relative).is_file()
