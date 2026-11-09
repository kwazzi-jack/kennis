"""A tag's colour (#627, sketch 2026-11-06-tag-colours-and-tab, part c).

Automatic from the name onto eight colours, or chosen and kept in the
store's `tags.yml`, where a coloured tag is written as a mapping holding
`colour` and `targets`. Every writer keeps a chosen colour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.errors import KennisError
from kennis.engine.tags import (
    TAG_COLOURS,
    TAGS_FILENAME,
    Anchor,
    colour_of,
    read_store,
    read_tags,
    tag_colour,
    with_tags,
    written,
)
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


def test_a_coloured_tag_is_written_as_a_mapping_and_read_back(tmp_path: Path):
    held = with_tags({}, ("calibration", "to-cite"), Anchor(PAPER_ID))
    path = tmp_path / TAGS_FILENAME

    path.write_text(written(held, colours={"calibration": "blue"}), encoding="utf-8")

    text = path.read_text(encoding="utf-8")
    assert "calibration:\n  colour: blue\n  targets:\n" in text
    assert "to-cite:\n- document:" in text
    store = read_store(path)
    assert store.tags == held
    assert store.colours == {"calibration": "blue"}
    assert read_tags(path) == held


def test_a_colour_for_a_tag_with_no_targets_is_not_written(tmp_path: Path):
    held = with_tags({}, ("a",), Anchor(PAPER_ID))

    assert "gone" not in written(held, colours={"gone": "red"})


@pytest.mark.parametrize(
    "text",
    [
        f"a:\n  colour: mauve\n  targets:\n  - document: {PAPER_ID}\n",
        f"a:\n  colour: red\n  targets:\n  - document: {PAPER_ID}\n  extra: 1\n",
        "a:\n  colour: red\n",
        f"a:\n  colour: 3\n  targets:\n  - document: {PAPER_ID}\n",
    ],
)
def test_a_colour_kennis_cannot_read_is_refused_with_its_path(
    tmp_path: Path, text: str
):
    path = tmp_path / TAGS_FILENAME
    path.write_text(text, encoding="utf-8")

    with pytest.raises(KennisError) as refusal:
        read_store(path)
    assert str(path) in str(refusal.value)


# ---------------------------------------------------------------------------
# Setting a colour, and keeping it


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def test_kennis_tag_sets_a_colour_without_a_passage(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    said = run("tag", "calibration", "--colour", "Purple")

    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "purple"}
    assert "purple" in said


def test_auto_clears_a_chosen_colour(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")
    run("tag", "calibration", "--colour", "purple")

    run("tag", "calibration", "--colour", "auto")

    assert read_store(corpus / TAGS_FILENAME).colours == {}


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

    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "red"}


def test_a_colour_is_committed(corpus: Path):
    from test_cli_tags import git

    run("tag", "calibration", f"id={PAPER_ID}")

    run("tag", "calibration", "--colour", "teal")

    assert git(corpus, "log", "-1", "--format=%s").startswith("tag(corpus):")
    assert git(corpus, "status", "--porcelain") == ""


def test_a_colour_for_a_tag_nothing_carries_is_refused(corpus: Path):
    said = refused("tag", "nowhere", "--colour", "teal")

    assert "nothing is tagged nowhere" in said
    assert not (corpus / TAGS_FILENAME).exists()


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
    """`#` begins a YAML comment, so the value must be written quoted."""
    held = with_tags({}, ("a",), Anchor(PAPER_ID))
    path = tmp_path / TAGS_FILENAME

    path.write_text(written(held, colours={"a": "#1f5fd1"}), encoding="utf-8")

    assert read_store(path).colours == {"a": "#1f5fd1"}


def test_kennis_tag_takes_a_hex_colour(corpus: Path):
    run("tag", "calibration", f"id={PAPER_ID}")

    run("tag", "calibration", "--colour", "#FFE600")

    assert read_store(corpus / TAGS_FILENAME).colours == {"calibration": "#ffe600"}
