"""A remembered note's title, written where a search can reach it.

`search "solver"` used to miss a note titled `Solver choice` whose body says
"We use quartical rather than cubical", because the chunker is given the
body and the title lives in frontmatter. Concern #243.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.context import (
    index_bundle,
    init_bundle,
    load_bundle_index,
    remember_in_bundle,
)
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.rag.search import search
from kennis.engine.remember import titled_body


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return init_bundle(tmp_path / "project").path


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_a_chosen_title_becomes_a_heading():
    assert titled_body("Solver choice", "We use quartical.") == (
        "# Solver choice\n\nWe use quartical."
    )


def test_a_derived_title_is_not_prepended():
    """`title_for` takes the body's first line, so prepending it would
    repeat the note's opening words back at itself. A derived title is
    already in the body by construction, which is why the caller passes
    None here rather than the title it derived."""
    assert titled_body(None, "We use quartical.") == "We use quartical."


def test_a_body_that_already_has_a_heading_is_left_alone():
    """The caller supplied their own. Two stacked headings is worse than a
    title that appears only in the frontmatter."""
    assert titled_body("Solver choice", "# Notes\n\nWe use quartical.") == (
        "# Notes\n\nWe use quartical."
    )


@pytest.mark.parametrize("opening", ["## Sub", "###### Deep", "  # Indented"])
def test_any_atx_heading_counts_as_the_bodys_own(opening: str):
    """Not only an H1. A body that opens at H2 was given that heading by
    someone, and `title_for` would have taken it as the title - so putting
    an H1 above it duplicates the same words one level up."""
    body = f"{opening}\n\nProse."
    assert titled_body("Chosen", body) == body


def test_leading_blank_lines_do_not_hide_a_heading():
    assert titled_body("Chosen", "\n\n# Notes\n\nProse.") == "\n\n# Notes\n\nProse."


def test_a_hash_that_is_not_a_heading_does_not_count():
    """`#tag` is not a heading - ATX needs a space after the hashes - and a
    note opening with one still wants its title."""
    assert titled_body("Chosen", "#tag and prose.") == "# Chosen\n\n#tag and prose."


# ---------------------------------------------------------------------------
# What it buys, end to end
# ---------------------------------------------------------------------------


def test_a_bundle_note_is_found_by_its_title(bundle: Path):
    """The failure that started this: a word that appears only in the title."""
    remember_in_bundle(bundle, "We use quartical rather than cubical.", title="Solver")
    index_bundle(bundle)

    hits = search(load_bundle_index(bundle), "solver", top_k=3, mode="bm25")

    assert hits


def test_the_title_is_in_the_file_as_a_heading(bundle: Path):
    note = remember_in_bundle(bundle, "We use quartical.", title="Solver choice")

    _, body = split_frontmatter(note.path.read_text(encoding="utf-8"))

    assert body.startswith("# Solver choice\n")


def test_a_note_with_a_derived_title_gains_no_heading(bundle: Path):
    note = remember_in_bundle(bundle, "We use quartical rather than cubical.")

    _, body = split_frontmatter(note.path.read_text(encoding="utf-8"))

    assert body.startswith("We use quartical")


# ---------------------------------------------------------------------------
# Deduplication, which the heading would otherwise break
# ---------------------------------------------------------------------------


def test_remembering_the_same_titled_text_twice_writes_one_file(bundle: Path):
    """The quiet breakage. A bundle deduplicates on the digest of what it
    holds, and once a heading is prepended the stored body is no longer the
    text that was given - so without a recorded digest the second call would
    write a second copy of a note kennis already had."""
    first = remember_in_bundle(bundle, "We use quartical.", title="Solver")

    second = remember_in_bundle(bundle, "We use quartical.", title="Solver")

    assert second.path == first.path
    assert (
        len([path for path in bundle.rglob("*.md") if path.name != "LANDING.md"]) == 2
    )


def test_the_digest_of_the_given_text_is_recorded(bundle: Path):
    note = remember_in_bundle(bundle, "We use quartical.", title="Solver")

    frontmatter, _ = split_frontmatter(note.path.read_text(encoding="utf-8"))

    assert frontmatter["source"]["sha256"]


def test_a_hand_written_file_without_a_digest_still_deduplicates(bundle: Path):
    """The fallback. Nothing kennis wrote is missing the digest, but a file
    a user wrote by hand has none - and kennis never added a heading to it,
    so hashing its body is the right answer for it."""
    path = bundle / "mine.md"
    path.write_text("---\ntitle: Mine\nowner: user\n---\n\nUnique prose.\n", "utf-8")

    note = remember_in_bundle(bundle, "Unique prose.")

    assert note.path == path
