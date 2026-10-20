"""The machine's projects: every bundle kennis has touched (14g, #512).

A list kept under the state directory, never in the corpus, which is
committed and synced. It records where bundles are and nothing else - no
content moves between them - so the window can show every project and a
search can cover them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.context import index_bundle, init_bundle, remember_in_bundle
from kennis.engine.context.projects import (
    ProjectListUnreadable,
    ProjectNotKnown,
    add_project,
    forget_project,
    known_projects,
    projects_path,
    record_project,
)
from kennis.engine.errors import ContextNotFound
from kennis.engine.settings import state_dir


@pytest.fixture(autouse=True)
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)


def a_project(root: Path) -> Path:
    """A workspace with a bundle, made by the engine, and its bundle."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return init_bundle(root).path


def names() -> list[str]:
    return [project.name for project in known_projects()]


# ---------------------------------------------------------------------------
# The list


def test_the_list_lives_in_the_state_directory():
    assert projects_path().parent == state_dir()


def test_no_project_is_known_before_one_is_touched():
    assert known_projects() == ()


def test_a_recorded_project_is_known_by_its_folder_s_name(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")

    (known,) = known_projects()

    assert known.name == "pipelines"
    assert known.bundle == bundle.resolve()
    assert known.present


def test_recording_a_known_project_again_does_not_rewrite_the_list(tmp_path: Path):
    """A search records the project it is run from, so recording must cost
    nothing once the project is listed."""
    bundle = a_project(tmp_path / "pipelines")
    before = projects_path().stat().st_mtime_ns

    assert record_project(bundle) is False

    assert projects_path().stat().st_mtime_ns == before
    assert names() == ["pipelines"]


def test_a_moved_project_is_listed_as_missing_rather_than_dropped(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    (bundle / "bundle.json").unlink()

    (known,) = known_projects()

    assert known.name == "pipelines"
    assert not known.present


def test_two_folders_of_one_name_are_told_apart_by_their_parents(tmp_path: Path):
    a_project(tmp_path / "work" / "thesis")
    a_project(tmp_path / "old" / "thesis")

    assert names() == ["old/thesis", "work/thesis"]


def test_a_forgotten_project_is_no_longer_known(tmp_path: Path):
    a_project(tmp_path / "pipelines")
    a_project(tmp_path / "thesis")

    forgotten = forget_project("pipelines")

    assert forgotten.name == "pipelines"
    assert names() == ["thesis"]


def test_forgetting_a_project_never_known_names_the_list(tmp_path: Path):
    a_project(tmp_path / "pipelines")

    with pytest.raises(ProjectNotKnown) as raised:
        forget_project("thesis")

    assert "thesis" in str(raised.value)
    assert raised.value.resolution == "kennis context list"


def test_a_folder_holding_a_bundle_can_be_added(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    projects_path().unlink()

    added = add_project(tmp_path / "pipelines")

    assert added.bundle == bundle.resolve()
    assert names() == ["pipelines"]


def test_the_bundle_itself_can_be_added(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    projects_path().unlink()

    add_project(bundle)

    assert names() == ["pipelines"]


def test_a_folder_with_no_bundle_is_refused(tmp_path: Path):
    (tmp_path / "empty").mkdir()

    with pytest.raises(ContextNotFound):
        add_project(tmp_path / "empty")

    assert known_projects() == ()


def test_an_unreadable_list_is_refused_and_named(tmp_path: Path):
    a_project(tmp_path / "pipelines")
    projects_path().write_text("{not json", encoding="utf-8")

    with pytest.raises(ProjectListUnreadable) as raised:
        known_projects()

    assert str(projects_path()) in str(raised.value)


# ---------------------------------------------------------------------------
# Where a project is recorded: wherever kennis touches a bundle


def test_making_a_bundle_records_its_project(tmp_path: Path):
    a_project(tmp_path / "pipelines")

    assert names() == ["pipelines"]


def test_remembering_into_a_bundle_records_its_project(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    projects_path().unlink()

    remember_in_bundle(bundle, "Solve per scan.", title=None, group=None)

    assert names() == ["pipelines"]


def test_indexing_a_bundle_records_its_project(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    remember_in_bundle(bundle, "Solve per scan.", title=None, group=None)
    projects_path().unlink()

    index_bundle(bundle)

    assert names() == ["pipelines"]


def test_syncing_a_bundle_records_its_project(tmp_path: Path):
    from kennis.engine.context.sync import sync_bundle

    bundle = a_project(tmp_path / "pipelines")
    projects_path().unlink()

    sync_bundle(bundle, tmp_path / "corpus")

    assert names() == ["pipelines"]


def test_searching_a_bundle_records_its_project(tmp_path: Path):
    from kennis.retrieval import search_scope

    bundle = a_project(tmp_path / "pipelines")
    remember_in_bundle(bundle, "Solve per scan.", title=None, group=None)
    index_bundle(bundle)
    projects_path().unlink()

    search_scope("context", "scan", bundle=bundle)

    assert names() == ["pipelines"]


def test_an_unreadable_list_does_not_stop_a_search(tmp_path: Path):
    """The list serves the window; a search that failed because of it would
    fail for a reason the person never asked about."""
    from kennis.retrieval import search_scope

    bundle = a_project(tmp_path / "pipelines")
    remember_in_bundle(bundle, "Solve per scan.", title=None, group=None)
    index_bundle(bundle)
    projects_path().write_text("{not json", encoding="utf-8")

    hits = search_scope("context", "scan", bundle=bundle)

    assert hits


# ---------------------------------------------------------------------------
# The commands


def test_context_list_names_each_project_and_where_it_is(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")

    result = CliRunner().invoke(main, ["context", "list"])

    assert result.exit_code == 0, result.output
    assert "pipelines" in result.output
    assert str(bundle.parent) in "".join(result.output.split())


def test_context_list_says_a_project_is_missing_and_how_to_forget_it(tmp_path: Path):
    bundle = a_project(tmp_path / "pipelines")
    (bundle / "bundle.json").unlink()

    result = CliRunner().invoke(main, ["context", "list"])

    assert result.exit_code == 0, result.output
    assert "missing" in result.output
    assert "kennis context forget pipelines" in result.output


def test_context_list_with_nothing_known_says_how_one_is_made():
    result = CliRunner().invoke(main, ["context", "list"])

    assert result.exit_code == 0, result.output
    assert "kennis context init" in result.output


def test_context_add_and_forget(tmp_path: Path):
    a_project(tmp_path / "pipelines")
    projects_path().unlink()
    runner = CliRunner()

    added = runner.invoke(main, ["context", "add", str(tmp_path / "pipelines")])
    assert added.exit_code == 0, added.output
    assert names() == ["pipelines"]

    forgotten = runner.invoke(main, ["context", "forget", "pipelines"])
    assert forgotten.exit_code == 0, forgotten.output
    assert names() == []
