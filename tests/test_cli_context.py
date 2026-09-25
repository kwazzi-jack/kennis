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
from kennis.engine.context import BUNDLE_DIRNAME, load_bundle_index
from kennis.engine.rag.search import search


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


# ---------------------------------------------------------------------------
# `kennis remember --context`
#
# Tested here rather than in `test_cli_remember.py` because the bundle, not
# the note, is what makes these true: the corpus half of that file gives
# every test a corpus and a lock, and this half must work without either.
# ---------------------------------------------------------------------------


@pytest.fixture
def bundle(workspace: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    return workspace / BUNDLE_DIRNAME


def bundle_notes(bundle: Path) -> list[Path]:
    """Every document the bundle holds that a person put there. `LANDING.md`
    and the dot-prefixed skeleton are scaffolding, not notes."""
    return sorted(
        path
        for path in bundle.rglob("*.md")
        if path.name != "LANDING.md"
        and not any(part.startswith(".") for part in path.relative_to(bundle).parts)
    )


def test_remember_context_writes_into_the_bundle(bundle: Path, run: CliRunner):
    result = run.invoke(
        main, ["remember", "--context", "This project calibrates in 4-minute chunks."]
    )

    assert result.exit_code == 0, result.output
    written = bundle_notes(bundle)
    assert len(written) == 1, written
    assert "4-minute chunks" in written[0].read_text(encoding="utf-8")


def test_remember_context_needs_no_corpus(bundle: Path, run: CliRunner):
    """A bundle belongs to one project; a corpus is machine-global. Writing
    a project's own note must not require the second to exist, and this test
    is run with no `KENNIS_CORPUS_ROOT` and no `corpus init`."""
    result = run.invoke(main, ["remember", "--context", "A local decision."])

    assert result.exit_code == 0, result.output
    assert len(bundle_notes(bundle)) == 1


def test_remember_context_does_not_commit_to_the_users_repository(
    workspace: Path, bundle: Path, run: CliRunner
):
    """The bundle sits inside a repository kennis does not own. Committing
    to it would take over the user's version control."""
    assert (
        run.invoke(main, ["remember", "--context", "A local decision."]).exit_code == 0
    )

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert log.stdout == ""
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert BUNDLE_DIRNAME in status.stdout


def test_remember_context_without_a_bundle_names_the_command_that_makes_one(
    workspace: Path, run: CliRunner
):
    result = run.invoke(main, ["remember", "--context", "A local decision."])

    assert result.exit_code != 0
    assert "kennis context init" in result.output


def test_remember_context_takes_the_title(bundle: Path, run: CliRunner):
    result = run.invoke(
        main, ["remember", "--context", "--title", "Chunking", "Four minutes."]
    )

    assert result.exit_code == 0, result.output
    assert [path.name for path in bundle_notes(bundle)] == ["Chunking.md"]


def test_remember_context_takes_a_group(bundle: Path, run: CliRunner):
    result = run.invoke(
        main, ["remember", "--context", "--group", "decisions", "Four minutes."]
    )

    assert result.exit_code == 0, result.output
    written = bundle_notes(bundle)
    assert [path.parent.name for path in written] == ["decisions"]


def test_remembering_the_same_thing_twice_writes_one_file(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    again = run.invoke(main, ["remember", "--context", "Four minutes."])

    assert again.exit_code == 0, again.output
    assert "nchanged" in again.output
    assert len(bundle_notes(bundle)) == 1


def test_remember_context_reads_a_file_and_standard_input(
    bundle: Path, run: CliRunner, tmp_path: Path
):
    """The three routes are resolved before the write path is chosen, so
    `--from` and a pipe have to reach the bundle too."""
    path = tmp_path / "jottings.md"
    path.write_text("# From a file\n\nFour minutes.\n", encoding="utf-8")

    assert (
        run.invoke(main, ["remember", "--context", "--from", str(path)]).exit_code == 0
    )
    piped = run.invoke(main, ["remember", "--context"], input="# Piped\n\nEight.\n")

    assert piped.exit_code == 0, piped.output
    assert sorted(path.name for path in bundle_notes(bundle)) == [
        "From a file.md",
        "Piped.md",
    ]


def test_no_index_with_context_is_refused_rather_than_ignored(
    bundle: Path, run: CliRunner
):
    """A bundle is not indexed yet (#169). A flag asking for the index to be
    skipped therefore has nothing to skip, and accepting it silently would
    tell the caller something was honoured that was never considered."""
    result = run.invoke(main, ["remember", "--context", "--no-index", "Four minutes."])

    assert result.exit_code != 0
    assert bundle_notes(bundle) == []


def test_remember_context_says_where_it_went(bundle: Path, run: CliRunner):
    """The path is named from the bundle directory down. `remember` writes
    to two different places, and a bundle-relative path on its own would not
    say which of them this was."""
    result = run.invoke(main, ["remember", "--context", "--title", "Chunking", "Four."])

    assert "Remembered" in result.output
    assert f"{BUNDLE_DIRNAME}/Chunking.md" in result.output


def test_quiet_remember_context_prints_nothing_on_success(bundle: Path, run: CliRunner):
    result = run.invoke(main, ["--quiet", "remember", "--context", "Four minutes."])

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert len(bundle_notes(bundle)) == 1


# ---------------------------------------------------------------------------
# `kennis context index`
# ---------------------------------------------------------------------------


def test_context_index_builds_an_index_inside_the_bundle(bundle: Path, run: CliRunner):
    """Inside, not beside: that is what lets the index be committed with the
    project and arrive working in a fresh clone."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["context", "index"])

    assert result.exit_code == 0, result.output
    assert (bundle / ".index" / "context" / "latest.json").is_file()


def test_context_index_does_not_commit_to_the_users_repository(
    workspace: Path, bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    assert run.invoke(main, ["context", "index"]).exit_code == 0

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert log.stdout == ""


def test_context_index_without_a_bundle_names_the_command_that_makes_one(
    workspace: Path, run: CliRunner
):
    result = run.invoke(main, ["context", "index"])

    assert result.exit_code != 0
    assert "kennis context init" in result.output


def test_indexing_an_empty_bundle_is_refused_rather_than_writing_nothing(
    bundle: Path, run: CliRunner
):
    """A bundle straight out of `init` holds only the landing file and the
    skeleton, both excluded from the index, so this is the first thing a new
    user meets."""
    result = run.invoke(main, ["context", "index"])

    assert result.exit_code != 0
    assert not (bundle / ".index").exists()
    # `build_index` refuses an empty collection on its own, so asserting only
    # the exit code would pass with the bundle wording removed. What is being
    # tested is that the reader is told this is their project's bundle and
    # what puts something in it.
    assert "context bundle" in result.output
    assert "kennis remember" in result.output


def test_context_index_uses_the_configured_chunk_size(
    bundle: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The command reads the chunking settings rather than the chunker's own
    defaults. Recorded in `binding.json`, which is what a second machine
    compares against its own configuration to decide whether to rebuild."""
    monkeypatch.setenv("KENNIS_CHUNKING_SIZE", "300")
    monkeypatch.setenv("KENNIS_CHUNKING_OVERLAP", "30")
    assert run.invoke(main, ["remember", "--context", "word " * 400]).exit_code == 0

    assert run.invoke(main, ["context", "index"]).exit_code == 0

    assert load_bundle_index(bundle).binding.chunking.size == 300


def test_a_remembered_note_is_searchable_after_indexing(bundle: Path, run: CliRunner):
    """The command-line half of the crossing test: two commands, and the
    second makes what the first wrote findable."""
    assert (
        run.invoke(
            main,
            ["remember", "--context", "Ionospheric screens need direction solutions."],
        ).exit_code
        == 0
    )
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    loaded = load_bundle_index(bundle)
    hits = search(loaded, "ionospheric screens", top_k=3, mode="bm25")
    assert hits


def test_quiet_context_index_prints_nothing_on_success(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["--quiet", "context", "index"])

    assert result.exit_code == 0, result.output
    assert result.output == ""
