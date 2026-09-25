"""Finding the `.context/` bundle that governs a directory, and scaffolding one.

The walk is the thing every other context command needs first, and the one
thing `design.md` does not specify - concern #225. It follows boepie's
`find_bundle`, including the decision that matters most: it keys on a
manifest *inside* the candidate directory rather than on the directory
existing, so a stray or half-made `.context/` cannot hijack it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kennis.engine.context import (
    BUNDLE_DIRNAME,
    MANIFEST_FILENAME,
    find_bundle,
    init_bundle,
    is_bundle_dir,
    workspace_root,
)


@pytest.fixture(autouse=True)
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The override is honoured before the walk, so it has to be absent for
    every test that is about the walk."""
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)


def a_workspace(root: Path) -> Path:
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# The walk


def test_a_bundle_is_found_in_the_directory_it_governs(tmp_path: Path):
    init_bundle(a_workspace(tmp_path))

    assert find_bundle(tmp_path) == tmp_path / BUNDLE_DIRNAME


def test_a_bundle_is_found_from_a_nested_subdirectory(tmp_path: Path):
    """The reason for walking at all: a command is run where the work is."""
    init_bundle(a_workspace(tmp_path))
    deep = tmp_path / "src" / "kennis" / "engine"
    deep.mkdir(parents=True)

    assert find_bundle(deep) == tmp_path / BUNDLE_DIRNAME


def test_no_bundle_anywhere_is_none_rather_than_an_error(tmp_path: Path):
    """ "No bundle" and "a bundle with no index" have different fixes, so the
    caller renders the error rather than this."""
    assert find_bundle(tmp_path) is None


def test_the_nearest_bundle_wins(tmp_path: Path):
    init_bundle(a_workspace(tmp_path))
    inner = a_workspace(tmp_path / "subproject")
    init_bundle(inner)

    assert find_bundle(inner / "deep") == inner / BUNDLE_DIRNAME


def test_a_directory_without_a_manifest_is_not_a_bundle(tmp_path: Path):
    """The decision boepie took and this takes: the marker is the manifest,
    not the directory. A half-made or hand-created `.context/` must not
    capture the walk and make the real one unreachable."""
    (tmp_path / "subproject" / BUNDLE_DIRNAME).mkdir(parents=True)
    init_bundle(a_workspace(tmp_path))

    assert not is_bundle_dir(tmp_path / "subproject" / BUNDLE_DIRNAME)
    assert find_bundle(tmp_path / "subproject") == tmp_path / BUNDLE_DIRNAME


def test_the_walk_does_not_stop_at_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A workspace inside a home directory is ordinary, so the walk goes to
    the filesystem root rather than stopping at `$HOME`.

    The bundle is *above* `$HOME` and the start is below it, so the walk has
    to pass through `$HOME` to succeed. Written the other way round first -
    bundle below `$HOME` - where the walk found it before reaching `$HOME`
    at all and an injection that stopped there passed the test.
    """
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    init_bundle(a_workspace(tmp_path))
    start = home / "project" / "src"
    start.mkdir(parents=True)

    assert find_bundle(start) == tmp_path / BUNDLE_DIRNAME


# ---------------------------------------------------------------------------
# The override


def test_the_override_is_honoured_before_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    elsewhere = a_workspace(tmp_path / "elsewhere")
    init_bundle(elsewhere)
    here = a_workspace(tmp_path / "here")
    init_bundle(here)
    monkeypatch.setenv("KENNIS_CONTEXT_DIR", str(elsewhere / BUNDLE_DIRNAME))

    assert find_bundle(here) == elsewhere / BUNDLE_DIRNAME


def test_a_mistyped_override_is_no_bundle_rather_than_the_wrong_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """boepie's rule, and the reason for it: an override that silently fell
    back to the walk would serve another project's knowledge under the
    impression it had been told which one to use."""
    here = a_workspace(tmp_path / "here")
    init_bundle(here)
    monkeypatch.setenv("KENNIS_CONTEXT_DIR", str(tmp_path / "typo"))

    assert find_bundle(here) is None


# ---------------------------------------------------------------------------
# Where a new bundle goes


def test_a_new_bundle_goes_at_the_git_root_not_the_working_directory(
    tmp_path: Path,
):
    """`.context/` belongs at the root of a workspace. Running the command
    three directories deep should not bury it there."""
    a_workspace(tmp_path)
    deep = tmp_path / "src" / "engine"
    deep.mkdir(parents=True)

    assert workspace_root(deep) == tmp_path


def test_without_a_git_root_a_bundle_goes_where_it_was_asked_for(tmp_path: Path):
    assert workspace_root(tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# What init writes


def test_init_writes_the_manifest_the_walk_keys_on(tmp_path: Path):
    created = init_bundle(a_workspace(tmp_path))
    manifest = created.path / MANIFEST_FILENAME

    assert manifest.is_file()
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert recorded["schema_version"] == 1
    assert recorded["created_at"]


def test_init_writes_a_landing_file_an_agent_is_meant_to_read(tmp_path: Path):
    created = init_bundle(a_workspace(tmp_path))

    landing = (created.path / "LANDING.md").read_text(encoding="utf-8")
    assert "LANDING.md" not in landing.splitlines()[0]
    assert ".skeleton.md" in landing


def test_the_skeleton_is_dotted_so_it_is_never_indexed(tmp_path: Path):
    """boepie needed a hardcoded name list because its skeleton was not
    dotted, and the skeleton then matched every query about its own section
    while answering none of them. Concern #227."""
    created = init_bundle(a_workspace(tmp_path))

    assert (created.path / ".skeleton.md").is_file()
    assert not (created.path / "skeleton.md").exists()


def test_the_skeleton_shows_the_frontmatter_a_bundle_file_carries(tmp_path: Path):
    created = init_bundle(a_workspace(tmp_path))
    skeleton = (created.path / ".skeleton.md").read_text(encoding="utf-8")

    assert skeleton.startswith("---\n")
    assert "owner: user" in skeleton


def test_init_writes_no_gitignore(tmp_path: Path):
    """boepie ignored `.index/`; design section 19 reverses that, because
    committing the bundle's index is what gives a fresh clone working
    search with no setup."""
    created = init_bundle(a_workspace(tmp_path))

    assert not (created.path / ".gitignore").exists()


def test_init_is_re_runnable(tmp_path: Path):
    first = init_bundle(a_workspace(tmp_path))
    (first.path / "mine.md").write_text("kept\n", encoding="utf-8")

    second = init_bundle(tmp_path)

    assert second.path == first.path
    assert not second.created
    assert (first.path / "mine.md").read_text(encoding="utf-8") == "kept\n"


def test_init_does_not_overwrite_an_edited_scaffold_file(tmp_path: Path):
    """The file most likely to be edited is the one `init` wrote.

    `LANDING.md` tells its reader to keep its table current, so editing it
    is the expected use - and a re-run that rewrote it would delete exactly
    the work the bundle exists to hold. The earlier tests only protected
    files the user *added*, which the scaffold loop never touches, so an
    injection removing the guard passed all of them.
    """
    created = init_bundle(a_workspace(tmp_path))
    landing = created.path / "LANDING.md"
    landing.write_text("# Ours\n\n| Question | Where |\n", encoding="utf-8")

    init_bundle(tmp_path)

    assert landing.read_text(encoding="utf-8").startswith("# Ours")


def test_init_restores_a_file_deleted_from_the_bundle(tmp_path: Path):
    """Re-runnable means converging, not just not-failing."""
    created = init_bundle(a_workspace(tmp_path))
    (created.path / "LANDING.md").unlink()

    init_bundle(tmp_path)

    assert (created.path / "LANDING.md").is_file()
