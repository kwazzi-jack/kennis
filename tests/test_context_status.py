"""What a bundle holds, and whether its index is in step.

The freshness half is the one worth testing hard. The corpus answers it with
git, against the commit its index records; a bundle has no commit kennis
may write, so the same question is answered by comparing the manifest's
recorded digests against the files on disk. Same `Freshness` value, entirely
different mechanism, and the counts have to come out the same.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.context import (
    bundle_status,
    index_bundle,
    init_bundle,
    remember_in_bundle,
)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return init_bundle(tmp_path / "project").path


def a_file(bundle: Path, relative: str, text: str) -> Path:
    path = bundle / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# What it holds
# ---------------------------------------------------------------------------


def test_an_empty_bundle_holds_nothing(bundle: Path):
    """Straight out of `init`: the landing file and the skeleton are
    scaffolding, not knowledge, so the count is zero rather than two."""
    status = bundle_status(bundle)

    assert status.document_count == 0
    assert status.groups == {}
    assert status.freshness is None


def test_documents_are_counted_per_group(bundle: Path):
    remember_in_bundle(bundle, "At the top.")
    remember_in_bundle(bundle, "A decision.", group="decisions")
    remember_in_bundle(bundle, "Another decision.", group="decisions")

    status = bundle_status(bundle)

    assert status.document_count == 3
    assert status.groups == {"": 1, "decisions": 2}


def test_a_header_that_will_not_parse_is_reported(bundle: Path):
    """The only place a broken header is reported outside a build. The
    loader emits a diagnostic while indexing, which a reader who has not
    indexed lately has never seen."""
    a_file(bundle, "broken.md", "---\ntitle: [unclosed\n---\n\nSomething.\n")
    remember_in_bundle(bundle, "A sound one.")
    # A file a user wrote by hand with no header at all. That is a file
    # without metadata, which is allowed, and reporting it would tell people
    # to fix something that is not wrong.
    a_file(bundle, "plain.md", "# Plain\n\nNo frontmatter here.\n")

    status = bundle_status(bundle)

    assert status.unreadable == ("broken.md",)
    assert status.document_count == 3


# ---------------------------------------------------------------------------
# Whether the index is in step
# ---------------------------------------------------------------------------


def test_a_freshly_built_index_is_in_step(bundle: Path):
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state == "in step"
    assert (freshness.added, freshness.changed, freshness.gone) == (0, 0, 0)


def test_a_file_written_since_the_build_counts_as_added(bundle: Path):
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    remember_in_bundle(bundle, "Solving is per scan.")

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.added == 1
    assert freshness.changed == 0


def test_an_edited_file_makes_the_index_stale(bundle: Path):
    """The fault case. An added document leaves the index incomplete; an
    edited one leaves it holding something false."""
    note = remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    # Same length, so a comparison that happened to be on file size rather
    # than on content would not notice.
    note.path.write_text(
        note.path.read_text(encoding="utf-8").replace("four", "five"),
        encoding="utf-8",
    )

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state == "stale"
    assert freshness.changed == 1


def test_a_deleted_file_makes_the_index_stale(bundle: Path):
    note = remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    note.path.unlink()

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state == "stale"
    assert freshness.gone == 1


def test_adding_alone_does_not_make_the_index_stale(bundle: Path):
    """The corpus's rule, and it transfers: between a write and the index
    that follows it the index holds less than the bundle, not something
    wrong. Incomplete is not the same fault as wrong."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    remember_in_bundle(bundle, "Solving is per scan.")

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state == "in step"


def test_the_comparison_is_against_recorded_digests_and_not_timestamps(
    bundle: Path,
):
    """Rewriting a file with the same text is not a change. A mtime-based
    check would call it one, and `remember --context` rewrites nothing - but
    a user's editor saving without edits does."""
    note = remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    note.path.write_text(note.path.read_text(encoding="utf-8"), encoding="utf-8")

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state == "in step"
    assert freshness.changed == 0


def test_freshness_is_never_unverifiable_for_a_bundle(bundle: Path):
    """The corpus's third state exists because git may not hold the commit
    an index was built from. A digest comparison has no such gap: the
    manifest records the digests, so the question is always answerable."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)
    a_file(bundle, "second.md", "Another.\n")

    freshness = bundle_status(bundle).freshness

    assert freshness is not None
    assert freshness.state != "unverifiable"
    assert freshness.unverifiable is None
