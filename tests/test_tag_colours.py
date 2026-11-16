"""A tag's colour (#627, sketch 2026-11-06-tag-colours-and-tab, part c).

Automatic from the name onto eight colours, or chosen and kept under
`colours` in the store's `annotations.json`. Every writer keeps a chosen
colour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from annotating import ANNOTATIONS, colours_in, whole_document, write_store
from kennis.engine.annotations import AnnotationStore, read_annotations
from kennis.engine.errors import KennisError
from kennis.engine.tags import TAG_COLOURS, colour_of, tag_colour
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper, refused, run

# Written by hand (#373).
EXPECTED_COLOURS = (
    "red",
    "orange",
    "yellow",
    "green",
    "teal",
    "blue",
    "purple",
    "pink",
)


def test_the_palette_is_the_one_written_down():
    assert TAG_COLOURS == EXPECTED_COLOURS


def test_an_automatic_colour_is_the_same_in_every_process():
    """crc32, not `hash`, which Python seeds per process: the same tag in
    two windows, or before and after a restart, must not change colour."""
    assert colour_of("calibration", {}) == "green"
    assert colour_of("to-read", {}) == "pink"
    assert colour_of("thesis", {}) == "red"


def test_automatic_colours_spread_over_the_palette():
    names = [f"tag-{number}" for number in range(200)]

    assert {colour_of(name, {}) for name in names} == set(TAG_COLOURS)


def test_a_chosen_colour_wins():
    assert colour_of("calibration", {"calibration": "pink"}) == "pink"


def test_a_colour_is_written_and_read_back(tmp_path: Path):
    store = AnnotationStore(
        (whole_document(PAPER_ID, ("calibration", "to-cite")),),
        {"calibration": "blue"},
    )

    write_store(tmp_path, store)

    assert read_annotations(tmp_path / ANNOTATIONS) == store


def test_a_colour_for_a_tag_with_no_targets_is_not_written(tmp_path: Path):
    write_store(
        tmp_path,
        AnnotationStore((whole_document(PAPER_ID, ("a",)),), {"gone": "red"}),
    )

    assert "gone" not in (tmp_path / ANNOTATIONS).read_text(encoding="utf-8")


@pytest.mark.parametrize("colour", ['"mauve"', "3", '"#12345"'])
def test_a_colour_kennis_cannot_read_is_refused_with_its_path(
    tmp_path: Path, colour: str
):
    path = tmp_path / ANNOTATIONS
    path.write_text(
        '{"format": 1, "annotations": [{"id": "0000000a", "document": '
        f'"{PAPER_ID}", "tags": ["a"], "created": "x"}}], '
        f'"colours": {{"a": {colour}}}}}',
        encoding="utf-8",
    )

    with pytest.raises(KennisError) as refusal:
        read_annotations(path)
    assert str(path) in str(refusal.value)


# ---------------------------------------------------------------------------
# Setting a colour, and keeping it


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def test_kennis_tag_sets_a_colour_without_a_passage(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    said = run("tag", "calibration", "--colour", "Purple")

    assert colours_in(corpus) == {"calibration": "purple"}
    assert "purple" in said


def test_auto_clears_a_chosen_colour(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    run("tag", "calibration", "--colour", "purple")

    run("tag", "calibration", "--colour", "auto")

    assert colours_in(corpus) == {}


def test_tagging_untagging_and_reindexing_keep_a_colour(corpus: Path):
    solving = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={solving}", "--colour", "red")
    run("tag", "calibration", f"id={PAPER_ID}")
    run("untag", "calibration", f"id={PAPER_ID}")
    (corpus / "literature" / "smirnov.md").write_text(
        (corpus / "literature" / "smirnov.md")
        .read_text(encoding="utf-8")
        .replace(
            "## Abstract", "## Preface\n\nA new first section here.\n\n## Abstract"
        ),
        encoding="utf-8",
    )
    run("corpus", "index")

    assert colours_in(corpus) == {"calibration": "red"}


def test_a_colour_is_committed(corpus: Path):
    from test_cli_tags import git

    run("tag", "calibration", f"id={PAPER_ID}")

    run("tag", "calibration", "--colour", "teal")

    assert git(corpus, "log", "-1", "--format=%s").startswith("tag(corpus):")
    assert git(corpus, "status", "--porcelain") == ""


def test_a_colour_for_a_tag_nothing_carries_is_refused(corpus: Path):
    said = refused("tag", "nowhere", "--colour", "teal")

    assert "nothing is tagged nowhere" in said
    assert not (corpus / ANNOTATIONS).exists()


def test_a_colour_outside_the_palette_is_refused_naming_the_palette(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    said = refused("tag", "calibration", "--colour", "mauve")

    assert "red, orange, yellow, green, teal, blue, purple, pink" in said


def test_a_tag_with_no_passage_and_no_colour_is_refused(corpus: Path):
    refused("tag", "calibration")


# ---------------------------------------------------------------------------
# A colour of one's own (#629)


@pytest.mark.parametrize(
    ("typed", "kept"),
    [("#1F5FD1", "#1f5fd1"), ("#abc", "#aabbcc"), (" Teal ", "teal")],
)
def test_a_hex_colour_is_kept_in_lowercase_and_widened(typed: str, kept: str):
    assert tag_colour(typed) == kept


@pytest.mark.parametrize("typed", ["#12345", "#gggggg", "1f5fd1", "mauve", ""])
def test_what_is_neither_a_name_nor_a_hex_is_refused(typed: str):
    with pytest.raises(KennisError) as refusal:
        tag_colour(typed)
    assert "or a hex colour such as #1f5fd1" in str(refusal.value)


def test_a_hex_colour_survives_the_file(tmp_path: Path):
    write_store(
        tmp_path,
        AnnotationStore((whole_document(PAPER_ID, ("a",)),), {"a": "#1f5fd1"}),
    )

    assert colours_in(tmp_path) == {"a": "#1f5fd1"}


def test_kennis_tag_takes_a_hex_colour(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    run("tag", "calibration", "--colour", "#FFE600")

    assert colours_in(corpus) == {"calibration": "#ffe600"}
