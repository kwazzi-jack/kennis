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
from kennis.cli.commands.context import context_model
from kennis.engine.context import BUNDLE_DIRNAME, load_bundle_index
from kennis.engine.rag.search import search
from kennis.engine.settings import load_settings


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


# ---------------------------------------------------------------------------
# `kennis context status`
# ---------------------------------------------------------------------------


def test_context_status_reports_what_the_bundle_holds(bundle: Path, run: CliRunner):
    assert (
        run.invoke(
            main, ["remember", "--context", "--group", "decisions", "Four minutes."]
        ).exit_code
        == 0
    )

    result = run.invoke(main, ["context", "status"])

    assert result.exit_code == 0, result.output
    assert str(bundle) in result.output
    assert "1 document" in result.output
    # One group and one document, so no breakdown: the row would repeat the
    # line above it.
    assert "decisions" not in result.output


def test_context_status_breaks_down_by_group_when_there_is_more_than_one(
    bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "At the top."]).exit_code == 0
    assert (
        run.invoke(
            main, ["remember", "--context", "--group", "decisions", "Four minutes."]
        ).exit_code
        == 0
    )

    result = run.invoke(main, ["context", "status"])

    assert result.exit_code == 0, result.output
    assert "(top level)" in result.output
    assert "decisions" in result.output


def test_context_status_on_an_empty_bundle_says_what_fills_it(
    bundle: Path, run: CliRunner
):
    result = run.invoke(main, ["context", "status"])

    assert result.exit_code == 0, result.output
    assert "0 documents" in result.output
    assert "kennis remember" in result.output


def test_context_status_names_the_command_that_indexes_an_unindexed_bundle(
    bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["context", "status"])

    assert "kennis context index" in result.output


def test_context_status_says_an_index_is_in_step(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["context", "status"])

    assert "in step" in result.output
    # Nothing left to do, so no command: a next step that changes nothing is
    # what concern #242 was about.
    assert "kennis context index" not in result.output


def test_context_status_counts_what_was_written_since_the_build(
    bundle: Path, run: CliRunner
):
    """`remember --context` does not index, so this is the ordinary state of
    a bundle rather than a brief window - which is why the count has to be
    on the line rather than implied by 'in step'."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0
    assert run.invoke(main, ["remember", "--context", "Per scan."]).exit_code == 0

    result = run.invoke(main, ["context", "status"])

    assert "1 document not yet indexed" in result.output
    assert "kennis context index" in result.output


def test_context_status_reports_a_stale_index(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0
    written = next(path for path in bundle.glob("*.md") if path.name != "LANDING.md")
    written.write_text(
        written.read_text(encoding="utf-8").replace("Four", "Eight"), encoding="utf-8"
    )

    result = run.invoke(main, ["context", "status"])

    assert "stale" in result.output
    assert "kennis context index" in result.output


def test_context_status_without_a_bundle_names_the_command_that_makes_one(
    workspace: Path, run: CliRunner
):
    result = run.invoke(main, ["context", "status"])

    assert result.exit_code != 0
    assert "kennis context init" in result.output


def test_quiet_context_status_prints_nothing(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["--quiet", "context", "status"])

    assert result.exit_code == 0, result.output
    assert result.output == ""


# ---------------------------------------------------------------------------
# `kennis context reset`
# ---------------------------------------------------------------------------


def a_pack_file(bundle: Path, relative: str) -> Path:
    """What a pack will write once packs exist: a document kennis owns."""
    path = bundle / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntitle: From a pack\nowner: pack\n---\n\nPack prose.\n", encoding="utf-8"
    )
    return path


def test_context_reset_removes_the_index_and_keeps_your_files(
    bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["context", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert not (bundle / ".index").exists()
    assert len(bundle_notes(bundle)) == 1


def test_context_reset_says_that_everything_was_yours(bundle: Path, run: CliRunner):
    """The plan asks for this in as many words: until packs exist, `reset`
    removes almost nothing, and that is worth stating rather than leaving a
    reader to discover."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["context", "reset", "--yes"])

    assert "your own files were left untouched" in result.output


def test_context_reset_with_nothing_to_remove_does_nothing(
    bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["context", "reset"])

    assert result.exit_code == 0, result.output
    assert "nothing to remove" in result.output
    assert len(bundle_notes(bundle)) == 1


def test_context_reset_asks_first_and_an_answer_of_no_removes_nothing(
    bundle: Path, run: CliRunner
):
    """Not recoverable through kennis: a bundle is in a repository kennis
    has no history of, so the only undo is the user's own."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["context", "reset"], input="n\n")

    assert result.exit_code != 0
    assert (bundle / ".index").is_dir()


def test_the_prompt_names_what_will_go(bundle: Path, run: CliRunner):
    a_pack_file(bundle, "conventions/naming.md")

    result = run.invoke(main, ["context", "reset"], input="n\n")

    assert "conventions/naming.md" in result.output


def test_context_reset_removes_a_file_kennis_owns(bundle: Path, run: CliRunner):
    applied = a_pack_file(bundle, "conventions/naming.md")
    assert run.invoke(main, ["remember", "--context", "Mine."]).exit_code == 0

    result = run.invoke(main, ["context", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert not applied.exists()
    assert len(bundle_notes(bundle)) == 1


def test_context_reset_names_the_command_that_rebuilds_the_index(
    bundle: Path, run: CliRunner
):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["context", "reset", "--yes"])

    assert "kennis context index" in result.output


def test_context_reset_without_a_bundle_names_the_command_that_makes_one(
    workspace: Path, run: CliRunner
):
    result = run.invoke(main, ["context", "reset", "--yes"])

    assert result.exit_code != 0
    assert "kennis context init" in result.output


def test_quiet_context_reset_prints_nothing(bundle: Path, run: CliRunner):
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["--quiet", "context", "reset", "--yes"])

    assert result.exit_code == 0, result.output
    assert result.output == ""


# ---------------------------------------------------------------------------
# `retrieval.context_method`
# ---------------------------------------------------------------------------


def test_a_bundle_is_indexed_lexically_by_default(bundle: Path, run: CliRunner):
    """The default is the design's decision, not a cautious fallback: a
    dense bundle index would turn `context init` into a model download and
    would make the binding match across machines much less likely, which is
    what committing the index is for."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    assert run.invoke(main, ["context", "index"]).exit_code == 0

    assert load_bundle_index(bundle).binding.model is None


def test_the_method_setting_is_what_asks_for_a_dense_leg(
    monkeypatch: pytest.MonkeyPatch,
):
    """Asked of the resolution directly rather than through `context index`.
    On a machine with no embedding backend both answers produce a lexical
    index, so a test that ran the command could not tell whether the setting
    was read - and the one written first passed with the setting ignored.
    `ollama` is named because building a `ModelBinding` for it reaches
    nothing: no download, no daemon, no network."""
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "ollama")

    monkeypatch.setenv("KENNIS_RETRIEVAL_CONTEXT_METHOD", "bm25")
    assert context_model(load_settings()) is None

    monkeypatch.setenv("KENNIS_RETRIEVAL_CONTEXT_METHOD", "hybrid")
    asked = context_model(load_settings())
    assert asked is not None
    assert asked.kind == "ollama"


def test_asking_for_hybrid_without_a_backend_is_a_lexical_index(
    bundle: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Not a failure. The corpus behaves the same way, and refusing would
    make a setting change break a command that has everything it needs to
    do something useful."""
    monkeypatch.setenv("KENNIS_RETRIEVAL_CONTEXT_METHOD", "hybrid")
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0

    result = run.invoke(main, ["context", "index"])

    assert result.exit_code == 0, result.output
    assert "lexical search only" in result.output
    assert load_bundle_index(bundle).binding.model is None


def test_a_default_context_search_reports_no_downgrade(bundle: Path, run: CliRunner):
    """`bm25` is what was asked for, so nothing was downgraded and there is
    nothing to report. This used to need a special case in `_fallback`; the
    setting is what removed it."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["search", "four minutes", "--collection", "context"])

    assert result.exit_code == 0, result.output
    assert "no dense leg" not in result.output


def test_asking_for_a_dense_context_search_reports_the_downgrade(
    bundle: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The other half. Someone who set the method to hybrid and got a
    lexical index is owed the sentence a corpus collection would get."""
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0
    monkeypatch.setenv("KENNIS_RETRIEVAL_CONTEXT_METHOD", "hybrid")

    result = run.invoke(main, ["search", "four minutes", "--collection", "context"])

    assert result.exit_code == 0, result.output
    assert "no dense leg" in result.output


def test_a_corpus_method_of_hybrid_does_not_reach_the_bundle(
    bundle: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The two settings are separate, which is the point of having two. A
    corpus asking for hybrid must not make a bundle report a downgrade it
    never asked to avoid."""
    monkeypatch.setenv("KENNIS_RETRIEVAL_CORPUS_METHOD", "hybrid")
    assert run.invoke(main, ["remember", "--context", "Four minutes."]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    result = run.invoke(main, ["search", "four minutes", "--collection", "context"])

    assert result.exit_code == 0, result.output
    assert "no dense leg" not in result.output
