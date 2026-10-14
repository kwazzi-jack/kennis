"""Each collection wears its own colour, wherever it appears.

Brian, 2026-10-12: "hard to decipher which is part of which collection".
One accent per collection and theme, chosen by meaning like the
strength scales (#416), so it lives in `gui/theme.py` and is measured
here: legible against both surfaces, apart from every other collection
for a deuteranope as well as for anyone else, and apart from the brand.
`sketches/2026-10-12-collection-colours.md` has the measurements.
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.gui.app import build_app
from kennis.gui.theme import (
    COLLECTION_COLOURS,
    CSS_COLOURS,
    CSS_COLOURS_DARK,
    DARK_GROUND,
    LIGHT_GROUND,
    stylesheet,
)

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}

# Written by hand (#373): the collections that wear a colour.
EXPECTED = {"literature", "docs", "notes", "context"}
THEMES = {
    "light": (LIGHT_GROUND, CSS_COLOURS),
    "dark": (DARK_GROUND, CSS_COLOURS_DARK),
}


def _rgb(colour: str) -> tuple[float, float, float]:
    digits = colour.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return red, green, blue


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _encoded(channel: float) -> float:
    channel = min(max(channel, 0.0), 1.0)
    return (
        12.92 * channel
        if channel <= 0.0031308
        else 1.055 * channel ** (1 / 2.4) - 0.055
    )


def _luminance(rgb: tuple[float, float, float]) -> float:
    red, green, blue = (_linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(
    one: tuple[float, float, float], other: tuple[float, float, float]
) -> float:
    light, dark = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    red, green, blue = (_linear(channel) for channel in rgb)
    x = 0.4124 * red + 0.3576 * green + 0.1805 * blue
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = 0.0193 * red + 0.1192 * green + 0.9505 * blue

    def transfer(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = (
        transfer(component / reference)
        for component, reference in zip((x, y, z), (0.95047, 1.0, 1.08883), strict=True)
    )
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


# Machado, Oliveira and Fernandes (2009), deuteranopia at severity 1.0.
_DEUTERANOPIA = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)


def _deuteranope(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    linear = [_linear(channel) for channel in rgb]
    red, green, blue = (
        _encoded(sum(m * c for m, c in zip(row, linear, strict=True)))
        for row in _DEUTERANOPIA
    )
    return red, green, blue


def _raised(ground: str, muted: str) -> tuple[float, float, float]:
    """The raised surface as drawn: the muted grey at 0x14 over the ground."""
    alpha = 0x14 / 255
    red, green, blue = (
        alpha * fore + (1 - alpha) * back
        for fore, back in zip(_rgb(muted), _rgb(ground), strict=True)
    )
    return red, green, blue


# ---------------------------------------------------------------------------
# The colours, measured
# ---------------------------------------------------------------------------


def test_the_collections_are_the_ones_written_down():
    assert set(COLLECTION_COLOURS) == EXPECTED
    assert all(set(themes) == set(THEMES) for themes in COLLECTION_COLOURS.values())


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_each_colour_is_legible_on_the_ground_and_on_a_card(theme: str):
    ground, palette = THEMES[theme]
    surfaces = (_rgb(ground), _raised(ground, palette["bright_black"]))

    for name, themes in COLLECTION_COLOURS.items():
        for surface in surfaces:
            assert _contrast(_rgb(themes[theme]), surface) >= 4.5, (name, theme)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_a_title_in_its_collections_colour_is_legible_on_its_own_band(theme: str):
    """The title is drawn in the collection's colour on the head's band,
    which is that colour at 9% over the ground - `color-mix(in srgb)`
    mixes the encoded channels, as this does."""
    ground, _ = THEMES[theme]
    for name, themes in COLLECTION_COLOURS.items():
        accent = _rgb(themes[theme])
        red, green, blue = (
            0.09 * fore + 0.91 * back
            for fore, back in zip(accent, _rgb(ground), strict=True)
        )
        assert _contrast(accent, (red, green, blue)) >= 4.5, (name, theme)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_pair_is_apart_for_everyone_and_for_a_deuteranope(theme: str):
    for (one, first), (other, second) in itertools.combinations(
        COLLECTION_COLOURS.items(), 2
    ):
        a, b = _rgb(first[theme]), _rgb(second[theme])
        assert math.dist(_lab(a), _lab(b)) >= 40, (one, other, theme)
        seen = math.dist(_lab(_deuteranope(a)), _lab(_deuteranope(b)))
        assert seen >= 20, (one, other, theme, seen)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_no_collection_wears_the_brand(theme: str):
    """The brand is "here" - a mark, a chosen control - and a collection
    in its colour would say something else in the same voice."""
    _, palette = THEMES[theme]
    brand = _lab(_rgb(palette["yellow"]))

    for name, themes in COLLECTION_COLOURS.items():
        assert math.dist(_lab(_rgb(themes[theme])), brand) >= 20, (name, theme)


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def css() -> str:
    return re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)


def test_each_theme_block_carries_every_collection():
    code = css()
    for name, themes in COLLECTION_COLOURS.items():
        for colour in themes.values():
            assert f"--collection-{name}: {colour};" in code, (name, colour)


def test_one_attribute_on_an_ancestor_chooses_the_colour():
    code = css()
    for name in EXPECTED:
        assert re.search(
            rf'\[data-collection="{name}"\] \{{\s*'
            rf"--collection: var\(--collection-{name}\);",
            code,
        ), name


@pytest.mark.parametrize(
    ("selector", "declaration"),
    [
        (".hit", "color-mix(in srgb, var(--collection) 45%, var(--rule))"),
        (".hit-head", "color-mix(in srgb, var(--collection) 9%, var(--ground))"),
        (".hit .title", "color: var(--collection)"),
        (".group-head", "border-bottom: 1px solid var(--collection)"),
        (".group-head .icon", "color: var(--collection)"),
        (".node .icon", "color: var(--collection)"),
        (".document .doc-bar", "var(--collection)"),
    ],
)
def test_each_place_reads_the_collection(selector: str, declaration: str):
    found = re.findall("^" + re.escape(selector) + r" \{([^}]*)\}", css(), re.M)

    assert found, selector
    assert any(declaration in body for body in found), (selector, found)


def test_an_open_card_thickens_its_frame_and_keeps_its_colour():
    """An open card says so by the weight of its frame, in the colour it
    already wears - all round, with no stripe down one side (Brian,
    2026-10-13)."""
    opened = re.search(r"\.hit:has\(details\[open\]\) \{([^}]*)\}", css())
    card = re.search(r"^\.hit \{([^}]*)\}", css(), re.M)

    assert opened and card
    assert "box-shadow: 0 0 0 1px var(--collection)" in opened.group(1)
    assert "border-left" not in card.group(1) + opened.group(1)


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    source = tmp_path / "sources" / "rivers.md"
    source.parent.mkdir(parents=True)
    source.write_text("# rivers\n\nRivers carry antenna sediment.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def test_a_hit_and_its_group_say_their_collection(client: TestClient):
    page = BeautifulSoup(
        client.get("/hits", params={"q": "antenna", "scope": "notes"}).text,
        "html.parser",
    )
    hit = page.find("li", class_="hit")
    head = page.find("h2", class_="group-head")

    assert isinstance(hit, Tag) and hit.get("data-collection") == "notes"
    assert isinstance(head, Tag) and head.get("data-collection") == "notes"


def test_a_document_page_says_its_collection(client: TestClient):
    held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
    page = BeautifulSoup(
        client.get(f"/document/notes/{held.documents[0].id}").text, "html.parser"
    )
    main_element = page.find("main")

    assert isinstance(main_element, Tag)
    assert main_element.get("data-collection") == "notes"


def test_the_pane_rows_say_their_collection(client: TestClient):
    page = BeautifulSoup(client.get("/").text, "html.parser")

    for name in ("literature", "docs", "notes"):
        assert page.find("li", attrs={"data-collection": name}) is not None, name
