"""Each annotation is highlighted in its tag's colour (#50, sketch
2026-11-17-highlight-tag-colours).

A custom highlight is painted by the rule for its name, so a colour is a
name: one of the eight named colours by a rule the stylesheet carries, a
typed hex colour by a rule the page carries for each one in use, and an
annotation with no tag in the brand colour, as before.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kennis.engine.tags import TAG_COLOURS
from kennis.gui.theme import (
    highlight_css,
    highlight_name,
    stylesheet,
    tag_colour_on,
)
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper, run
from test_gui_tags import opened, page_of


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def test_a_named_colour_a_hex_colour_and_none_each_have_a_name() -> None:
    assert highlight_name("annotation", "red") == "annotation-red"
    assert highlight_name("annotation", "#8a5a00") == "annotation-8a5a00"
    assert highlight_name("annotation", "") == "annotation"
    assert highlight_name("annotated-passage", "teal") == "annotated-passage-teal"


def test_a_value_that_is_no_colour_has_no_name() -> None:
    with pytest.raises(ValueError):
        highlight_name("annotation", "red; } body { display: none")


def _rule_of(css: str, name: str) -> str:
    found = re.search(r"::highlight\(" + re.escape(name) + r"\)[^{]*\{([^}]*)\}", css)
    assert found is not None, f"no rule for {name}"
    return found.group(1)


def test_the_stylesheet_paints_every_named_colour_in_that_colour() -> None:
    sheet = stylesheet()
    for colour in TAG_COLOURS:
        for prefix in ("annotation", "annotated-passage"):
            rule = _rule_of(sheet, f"{prefix}-{colour}")
            assert f"var(--tag-{colour})" in rule
            assert "--brand" not in rule


def test_an_annotation_with_no_tag_keeps_the_brand_colour() -> None:
    assert "var(--brand)" in _rule_of(stylesheet(), "annotation")


def test_a_hex_colour_is_painted_by_each_theme_s_value_under_its_guards() -> None:
    css = highlight_css(["#8a5a00", "red", "#1f5fd1"])

    for colour in ("8a5a00", "1f5fd1"):
        light = tag_colour_on(f"#{colour}", "light")
        dark = tag_colour_on(f"#{colour}", "dark")
        assert light != dark, "the fixture no longer exercises the themes"
        for prefix in ("annotation", "annotated-passage"):
            assert f"::highlight({prefix}-{colour})" in css
        declared = re.findall(rf"--highlight-{colour}:\s*(#[0-9a-f]{{6}})", css)
        assert declared == [light, dark, dark]
    assert "@media (prefers-color-scheme: dark)" in css
    assert 'html:not([data-theme="light"])' in css
    assert 'html[data-theme="dark"]' in css
    assert "red" not in css


def test_no_hex_colour_needs_no_rule() -> None:
    assert highlight_css(["red", "teal"]) == ""


def _highlights_on(corpus: Path) -> tuple[list[dict[str, object]], str]:
    client = opened()
    page = page_of(client, f"/document/literature/{PAPER_ID}")
    data = page.select_one("script[data-annotations]")
    assert data is not None
    styles = "\n".join(style.get_text() for style in page.select("style"))
    return json.loads(data.get_text()), styles


def test_an_annotation_is_painted_by_its_first_tag_s_colour(corpus: Path) -> None:
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "zeta,alpha", f"id={PAPER_ID}", f"chunk={chunk}")
    run("tag", "--colour", "red", "zeta")
    run("tag", "--colour", "teal", "alpha")

    (drawn,), _ = _highlights_on(corpus)

    # Stored sorted, so `alpha` is first whichever was typed first.
    assert drawn["paint"] == "annotation-teal"


def test_a_hex_coloured_tag_is_painted_by_a_rule_the_page_carries(corpus: Path) -> None:
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "odd", f"id={PAPER_ID}", f"chunk={chunk}")
    run("tag", "--colour", "#8a5a00", "odd")

    (drawn,), styles = _highlights_on(corpus)

    assert drawn["paint"] == "annotation-8a5a00"
    assert "::highlight(annotation-8a5a00)" in styles


def test_a_passage_kept_to_a_tag_is_painted_by_that_tag_s_colour(corpus: Path) -> None:
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "odd", f"id={PAPER_ID}", f"chunk={chunk}")
    run("tag", "--colour", "#8a5a00", "odd")
    client = opened()

    page = page_of(client, "/?q=antenna&scope=literature&tag=odd")

    (passage,) = page.select("[data-annotated]")
    (annotated,) = json.loads(str(passage["data-annotated"]))
    assert annotated["paint"] == "annotated-passage-8a5a00"
    styles = "\n".join(style.get_text() for style in page.select("style"))
    assert "::highlight(annotated-passage-8a5a00)" in styles
