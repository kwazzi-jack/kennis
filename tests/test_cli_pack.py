"""`kennis pack validate` at the command line. Milestone 7 unit 2.

The engine tests decide what is found; these decide what a reader is told
and what a pipeline's exit code is.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.locking import corpus_lock
from kennis.engine.pack.validate import content_digest

HEADER = """
kennis:
  schema_version: 1
pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    return tmp_path


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(run: CliRunner, isolated: Path) -> Path:
    result = run.invoke(main, ["corpus", "init"])
    assert result.exit_code == 0, result.output
    return isolated / "corpus"


def a_provider(root: Path, run: CliRunner) -> Path:
    """A pack with content, updated, as a provider would hand it over."""
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / "notes" / "conventions.md").write_text("Recipes.\n", encoding="utf-8")
    path = root / "p.ken.yml"
    path.write_text(
        HEADER + "corpus:\n  notes:\n    - source: notes/\n", encoding="utf-8"
    )
    assert run.invoke(main, ["pack", "update", str(path)]).exit_code == 0
    return path


def a_pack_file(root: Path, body: str = HEADER) -> Path:
    path = root / "stimela.ken.yml"
    path.write_text(body, encoding="utf-8")
    return path


def test_init_writes_a_file_named_for_the_pack(
    run: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)

    result = run.invoke(main, ["pack", "init", "--id", "boepie", "--name", "n"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "boepie.ken.yml").is_file()


def test_init_refuses_an_existing_file_without_naming_a_command(
    run: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`PackInvalid` points at `kennis pack validate` by default, and
    validating the file you just failed to overwrite answers a question
    nobody asked. Found by running the command; rule 4.4 is about commands
    that do not run, and this is one that runs and does not help."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "boepie.ken.yml").write_text("corpus: {}\n", encoding="utf-8")

    result = run.invoke(main, ["pack", "init", "--id", "boepie", "--name", "n"])

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert "kennis pack validate" not in result.output


def test_init_then_validate_is_a_clean_round_trip(
    run: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The scaffold is the first pack file every provider has, so a scaffold
    its own validator complains about would be the worst possible start."""
    monkeypatch.chdir(tmp_path)
    run.invoke(main, ["pack", "init", "--id", "boepie", "--name", "n"])

    result = run.invoke(main, ["pack", "validate", "boepie.ken.yml"])

    assert result.exit_code == 0, result.output


def test_a_valid_pack_exits_zero_and_names_it(run: CliRunner, tmp_path: Path):
    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "boepie" in result.output
    assert "0.1.0" in result.output


def test_a_pack_with_no_generated_block_says_no_digest_was_checked(
    run: CliRunner, tmp_path: Path
):
    """A bare "valid" would use one word for two different amounts of
    checking, and a forgotten `pack update` is exactly what a release
    pipeline runs this command to catch."""
    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path))])

    assert "no digest was checked" in result.output
    assert "Checked" in result.output


def test_a_stale_digest_exits_non_zero_so_a_pipeline_stops(
    run: CliRunner, tmp_path: Path
):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "one.md").write_text("Edited.\n", encoding="utf-8")
    body = (
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + "generated:\n"
        + '  at: "2026-09-26T00:00:00Z"\n'
        + '  by: "kennis 0.2.0"\n'
        + "  content:\n    notes:\n      - source: notes/\n        files:\n"
        + f'          "one.md": "{content_digest(b"stale")}"\n'
    )

    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path, body))])

    assert result.exit_code == 1
    assert "notes/one.md" in result.output


def test_a_digest_problem_names_the_command_that_fixes_it_once(
    run: CliRunner, tmp_path: Path
):
    """Rule 4.4, now satisfiable: `kennis pack update` exists. Printed once
    beside the count rather than on each finding, because all three digest
    findings have the same cause and the same fix. Concern #258."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "one.md").write_text("Body.\n", encoding="utf-8")
    (notes / "two.md").write_text("Body.\n", encoding="utf-8")
    body = (
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + "generated:\n"
        + '  at: "2026-09-26T00:00:00Z"\n'
        + '  by: "kennis 0.2.0"\n'
        + "  content:\n    notes:\n      - source: notes/\n        files: {}\n"
    )
    path = a_pack_file(tmp_path, body)

    result = run.invoke(main, ["pack", "validate", str(path)])

    assert result.output.count("kennis pack update") == 1
    assert str(path) in result.output
    assert "2 files disagree" in result.output


def test_one_stale_file_is_reported_in_the_singular(run: CliRunner, tmp_path: Path):
    """Found by running the command rather than by a test: the noun was
    pluralised and the verb was not, so a single stale file read "1 file
    disagree"."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "one.md").write_text("Body.\n", encoding="utf-8")
    body = (
        HEADER
        + "corpus:\n  notes:\n    - source: notes/\n"
        + "generated:\n"
        + '  at: "2026-09-26T00:00:00Z"\n'
        + '  by: "kennis 0.2.0"\n'
        + "  content:\n    notes:\n      - source: notes/\n        files: {}\n"
    )

    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path, body))])

    assert "1 file disagrees" in result.output


def test_a_version_refusal_does_not_suggest_editing_the_file(
    run: CliRunner, tmp_path: Path
):
    """Section 5 step 1: a pack needing a feature that does not exist has a
    different fix, and an author who edits the file has misread the message."""
    body = HEADER.replace(
        "  schema_version: 1", '  schema_version: 1\n  min_version: "99.0"'
    )

    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path, body))])

    assert result.exit_code == 1
    assert "upgrade" in result.output
    assert "pack update" not in result.output


def test_an_unparseable_file_reports_the_field_and_does_not_traceback(
    run: CliRunner, tmp_path: Path
):
    body = (
        "kennis:\n  schema_version: not-a-number\n"
        "pack:\n  id: a\n  name: n\n  version: '1'\n"
    )

    result = run.invoke(main, ["pack", "validate", str(a_pack_file(tmp_path, body))])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "kennis.schema_version" in result.output


def test_a_path_that_is_not_there_is_refused_by_the_argument(
    run: CliRunner, tmp_path: Path
):
    """click checks it, so the engine's own `PackInvalid` for a missing file
    is a second line of defence for a caller that is not the command line."""
    result = run.invoke(main, ["pack", "validate", str(tmp_path / "absent.ken.yml")])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# `pack add`
# ---------------------------------------------------------------------------


def test_add_installs_a_pack_into_the_corpus_store(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    path = a_provider(tmp_path / "provider", run)

    result = run.invoke(main, ["pack", "add", str(path)])

    assert result.exit_code == 0, result.output
    assert "Installed" in result.output
    assert (corpus / "packs" / "boepie" / "notes" / "conventions.md").is_file()


def test_add_without_a_corpus_names_the_command_that_makes_one(
    run: CliRunner, isolated: Path
):
    """Checked before the engine is reached, so every command fails the same
    way rather than each discovering it somewhere different."""
    path = a_provider(isolated / "provider", run)

    result = run.invoke(main, ["pack", "add", str(path)])

    assert result.exit_code != 0
    assert "kennis corpus init" in result.output


def test_a_second_add_says_nothing_changed(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """A provider calls this on every run, so the common case is this one."""
    del corpus
    path = a_provider(tmp_path / "provider", run)
    run.invoke(main, ["pack", "add", str(path)])

    result = run.invoke(main, ["pack", "add", str(path)])

    assert result.exit_code == 0, result.output
    assert "Unchanged" in result.output


def test_a_damaged_store_is_repaired_and_says_so(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """`Repaired` rather than `Installed`: "your provider shipped something
    new" and "what was here was damaged" are different facts, and a reader
    seeing the second twice has something to investigate."""
    path = a_provider(tmp_path / "provider", run)
    run.invoke(main, ["pack", "add", str(path)])
    (corpus / "packs" / "boepie" / "notes" / "conventions.md").unlink()

    result = run.invoke(main, ["pack", "add", str(path)])

    assert "Repaired" in result.output
    assert (corpus / "packs" / "boepie" / "notes" / "conventions.md").is_file()


def test_add_does_not_name_a_command_that_does_not_exist(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """Rule 4.4 again. "Installed" implies the content is searchable and
    it is not, so the report says so - and it names the one command that
    changes that and exists. `corpus sync` does not exist yet, so it is
    described rather than named; this test changes when it is built."""
    del corpus
    path = a_provider(tmp_path / "provider", run)

    result = run.invoke(main, ["pack", "add", str(path)])

    assert "nothing is materialised yet" in result.output
    assert "kennis context sync" in result.output
    assert "corpus sync" not in result.output


def test_the_reminder_is_not_repeated_on_an_unchanged_add(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    del corpus
    path = a_provider(tmp_path / "provider", run)
    run.invoke(main, ["pack", "add", str(path)])

    result = run.invoke(main, ["pack", "add", str(path)])

    assert "not in the corpus yet" not in result.output


def test_a_pack_whose_digests_are_stale_installs_nothing(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """The installing side re-checks what `pack validate` checks, because
    nothing makes a provider run it."""
    path = a_provider(tmp_path / "provider", run)
    (tmp_path / "provider" / "notes" / "conventions.md").write_text(
        "Edited after the update.\n", encoding="utf-8"
    )

    result = run.invoke(main, ["pack", "add", str(path)])

    assert result.exit_code != 0
    assert not (corpus / "packs" / "boepie").exists()


def test_add_is_refused_while_the_corpus_is_locked(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """`timeout=0`, so a second caller is told the corpus is busy rather
    than blocking - which for an automated provider run means a failure it
    can retry, not a hang nobody sees."""
    path = a_provider(tmp_path / "provider", run)

    with corpus_lock(corpus):
        result = run.invoke(main, ["pack", "add", str(path)])

    assert result.exit_code != 0
    assert "another kennis command is using the corpus" in result.output


# ---------------------------------------------------------------------------
# list, status and remove. Milestone 7 unit 6.
# ---------------------------------------------------------------------------


def a_second_provider(root: Path, run: CliRunner, *, identifier: str) -> Path:
    """Another provider shipping the same documentation project.

    Two packs declaring one item is the state `pack status` exists to
    report, and it takes two providers to produce it.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        HEADER.replace("id: boepie", f"id: {identifier}")
        + 'corpus:\n  docs:\n    - project: stimela\n      base_url: "https://x/"\n',
        encoding="utf-8",
    )
    assert run.invoke(main, ["pack", "update", str(path)]).exit_code == 0
    return path


def test_list_names_every_installed_pack(run: CliRunner, corpus: Path, isolated: Path):
    path = a_provider(isolated / "provider", run)
    assert run.invoke(main, ["pack", "add", str(path)]).exit_code == 0

    result = run.invoke(main, ["pack", "list"])

    assert result.exit_code == 0, result.output
    assert "boepie" in result.output
    assert "0.1.0" in result.output


def test_list_says_so_when_there_are_none(run: CliRunner, corpus: Path):
    result = run.invoke(main, ["pack", "list"])

    assert result.exit_code == 0, result.output
    assert "no packs installed" in result.output


def test_status_reports_when_a_pack_was_added(
    run: CliRunner, corpus: Path, isolated: Path
):
    path = a_provider(isolated / "provider", run)
    assert run.invoke(main, ["pack", "add", str(path)]).exit_code == 0

    result = run.invoke(main, ["pack", "status"])

    assert result.exit_code == 0, result.output
    assert "boepie" in result.output
    assert "added " in result.output


def test_status_reports_an_overlap_and_names_the_owner(
    run: CliRunner, corpus: Path, isolated: Path
):
    """The line the design says must be persistent state rather than a
    sentence printed once inside an automated run."""
    first = a_second_provider(isolated / "one", run, identifier="alpha")
    second = a_second_provider(isolated / "two", run, identifier="beta")
    assert run.invoke(main, ["pack", "add", str(first)]).exit_code == 0
    assert run.invoke(main, ["pack", "add", str(second)]).exit_code == 0

    result = run.invoke(main, ["pack", "status"])

    assert result.exit_code == 0, result.output
    assert "stimela" in result.output
    assert "owns it" in result.output


def test_status_reports_a_store_that_does_not_verify(
    run: CliRunner, corpus: Path, isolated: Path
):
    path = a_provider(isolated / "provider", run)
    assert run.invoke(main, ["pack", "add", str(path)]).exit_code == 0
    (corpus / "packs" / "boepie" / "notes" / "conventions.md").unlink()

    result = run.invoke(main, ["pack", "status"])

    assert result.exit_code == 0, result.output
    assert "not believed" in result.output


def test_remove_drops_the_pack_and_says_what_it_did_not_reach(
    run: CliRunner, corpus: Path, isolated: Path
):
    path = a_provider(isolated / "provider", run)
    assert run.invoke(main, ["pack", "add", str(path)]).exit_code == 0

    result = run.invoke(main, ["pack", "remove", "boepie"])

    assert result.exit_code == 0, result.output
    assert "Removed" in result.output
    assert "untouched" in result.output
    assert not (corpus / "packs" / "boepie").exists()


def test_removing_a_pack_that_is_not_there_fails_with_the_command_to_run(
    run: CliRunner, corpus: Path
):
    result = run.invoke(main, ["pack", "remove", "nosuch"])

    assert result.exit_code != 0
    assert "nosuch" in result.output
    assert "kennis pack list" in result.output


def test_remove_refuses_while_another_command_holds_the_corpus(
    run: CliRunner, corpus: Path, isolated: Path
):
    """A mutation, so it takes the lock every other mutation takes."""
    path = a_provider(isolated / "provider", run)
    assert run.invoke(main, ["pack", "add", str(path)]).exit_code == 0

    with corpus_lock(corpus):
        result = run.invoke(main, ["pack", "remove", "boepie"])

    assert result.exit_code != 0
    assert "another kennis command is using the corpus" in result.output
