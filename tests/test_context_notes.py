"""Writing prose into a `.context/` bundle.

The engine half of `kennis remember --context`. A bundle is not a corpus
collection - no surrogate identifiers, no `Uniqueness` record, and its
repository belongs to the user - so this is a second write path rather than
a parameter on `remember()`. Concerns #169 and #226.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kennis.engine.context import (
    bundle_documents,
    init_bundle,
    remember_in_bundle,
)
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return init_bundle(tmp_path).path


def frontmatter_of(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), text
    block = text.split("---\n", 2)[1]
    parsed = yaml.safe_load(block)
    assert isinstance(parsed, dict)
    return parsed


def test_a_note_is_written_into_the_bundle(bundle: Path):
    note = remember_in_bundle(bundle, "This project images in 2 GHz sub-bands.")

    assert note.path.is_file()
    assert note.path.parent == bundle
    assert "2 GHz sub-bands" in note.path.read_text(encoding="utf-8")


def test_the_title_comes_from_the_first_line(bundle: Path):
    note = remember_in_bundle(bundle, "Imaging conventions\n\nWe use sub-bands.")

    assert note.title == "Imaging conventions"
    assert note.path.name == "Imaging conventions.md"


def test_an_explicit_title_wins(bundle: Path):
    note = remember_in_bundle(bundle, "We use sub-bands.", title="Imaging")

    assert note.title == "Imaging"
    assert note.path.name == "Imaging.md"


def test_the_frontmatter_marks_it_as_the_users_own(bundle: Path):
    """`owner: user` is what the pack resolution table keys on, which is why
    it is written now rather than retrofitted when packs arrive."""
    note = remember_in_bundle(bundle, "We use sub-bands.", title="Imaging")
    recorded = frontmatter_of(note.path)

    assert recorded["owner"] == "user"
    assert recorded["title"] == "Imaging"
    source = recorded["source"]
    assert isinstance(source, dict)
    assert source["via"] == "remember"


def test_a_group_puts_it_in_a_subdirectory(bundle: Path):
    note = remember_in_bundle(
        bundle, "We use sub-bands.", title="Imaging", group="conventions"
    )

    assert note.path == bundle / "conventions" / "Imaging.md"
    assert note.relative_path == "conventions/Imaging.md"


def test_a_nested_group_is_created(bundle: Path):
    """A bundle's directories are the user's own invention, so a group may
    be any depth."""
    note = remember_in_bundle(
        bundle, "Gains.", title="Gains", group="calibration/gains"
    )

    assert note.path == bundle / "calibration" / "gains" / "Gains.md"


def test_saying_the_same_thing_twice_writes_one_file(bundle: Path):
    """An agent repeating itself is the expected case once there is an MCP
    server, and two identical files would both answer every query that
    matched either."""
    first = remember_in_bundle(bundle, "We image in 2 GHz sub-bands.")
    second = remember_in_bundle(bundle, "We image in 2 GHz sub-bands.")

    assert first.outcome is Outcome.ADDED
    assert second.outcome is Outcome.UNCHANGED
    assert second.path == first.path
    assert bundle_documents(bundle) == [first.path]


def test_a_duplicate_is_recognised_across_groups(bundle: Path):
    """The digest is of the body, so the same prose filed elsewhere is still
    the same prose."""
    first = remember_in_bundle(bundle, "Gains solve per antenna.", title="A")
    second = remember_in_bundle(
        bundle, "Gains solve per antenna.", title="B", group="deep"
    )

    assert second.outcome is Outcome.UNCHANGED
    assert second.path == first.path


def test_two_different_notes_with_one_first_line_both_survive(bundle: Path):
    """The filename comes from the title, so two notes can want the same
    one. Neither may overwrite the other."""
    first = remember_in_bundle(bundle, "Imaging\n\nSub-bands.")
    second = remember_in_bundle(bundle, "Imaging\n\nSomething else entirely.")

    assert second.outcome is Outcome.ADDED
    assert second.path != first.path
    assert first.path.is_file() and second.path.is_file()


def test_a_title_that_would_be_hidden_is_not(bundle: Path):
    """A dot-prefixed name is excluded from the index, so a note titled
    `.env notes` would be written and then be unfindable forever. The corpus
    strips a leading dot for the same reason one scope up."""
    note = remember_in_bundle(bundle, "Keys live outside git.", title=".env notes")

    assert not note.path.name.startswith(".")


def test_nothing_to_remember_is_an_error(bundle: Path):
    with pytest.raises(InputError):
        remember_in_bundle(bundle, "   \n\n  ")


def test_the_landing_file_is_not_treated_as_a_duplicate_source(bundle: Path):
    """`LANDING.md` has no frontmatter and is scanned like anything else;
    remembering its text would be a strange thing to do, but the scan must
    not crash on a file that is not a remembered note."""
    landing = (bundle / "LANDING.md").read_text(encoding="utf-8")
    note = remember_in_bundle(bundle, landing[:400], title="Copy")

    assert note.outcome is Outcome.ADDED


def test_kennis_does_not_commit_to_the_users_repository(bundle: Path):
    """The bundle lives inside a repository kennis does not own. Committing
    to it would take over the user's version control."""
    import subprocess

    root = bundle.parent
    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=root,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    before = subprocess.run(
        ["git", "rev-list", "--all", "--count"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()

    remember_in_bundle(bundle, "We image in 2 GHz sub-bands.")

    after = subprocess.run(
        ["git", "rev-list", "--all", "--count"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()
    assert before == after
