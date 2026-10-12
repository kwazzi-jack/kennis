"""Every choice the window offers is a dropdown, a segmented control, a
radio list or a checkbox by one rule, and every input is drawn.

Brian, 2026-10-12: the settings as dropdowns like kennis's own, the
other choices made by a rule, and the radio buttons drawn as the mockup
drew them. The rule is in `sketches/2026-10-12-controls.md`; the table
below is the same rule written down a second time, by hand, so that a
control changing kind fails here rather than passing because the page
and the table were generated from one source (#373).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui.app import build_app

TOKEN = "a-test-token"

# Which kind each control is, written by hand. A route, how to find the
# control on it, and the kind.
EXPECTED_KINDS: list[tuple[str, str, str]] = [
    ("/settings", "theme", "dropdown"),
    ("/settings", "face", "dropdown"),
    ("/settings", "size", "dropdown"),
    ("/settings", "spacing", "dropdown"),
    ("/settings", "width", "dropdown"),
    ("/settings", "strength", "dropdown"),
    ("/settings", "labels", "dropdown"),
    ("/settings", "scale", "radio list"),
    ("/index", "collection", "segmented"),
    ("/remember", "target", "segmented"),
    ("/add?kind=file", "collection", "segmented"),
    ("/add?kind=group", "collection-1", "segmented"),
]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def kind_of(page: str, name: str) -> str:
    """What kind of control carries the field `name` on `page`."""
    document = BeautifulSoup(page, "html.parser")
    select = document.find("select", attrs={"name": name})
    radios = document.find_all("input", attrs={"type": "radio", "name": name})
    if isinstance(select, Tag):
        assert not radios, name
        return "dropdown"
    assert radios, f"no control named {name}"
    holders = {id(radio.find_parent(class_="segmented")) for radio in radios}
    if all(radio.find_parent(class_="segmented") is not None for radio in radios):
        assert len(holders) == 1, "one segmented control, not several"
        return "segmented"
    if all(radio.find_parent(class_="radio-list") is not None for radio in radios):
        return "radio list"
    return "loose radios"


@pytest.mark.parametrize(("route", "name", "kind"), EXPECTED_KINDS)
def test_each_choice_is_the_kind_the_rule_gives_it(
    client: TestClient, route: str, name: str, kind: str
):
    answer = client.get(route)

    assert answer.status_code == 200, route
    assert kind_of(answer.text, name) == kind


def test_a_segmented_button_is_its_label_and_keeps_its_radio(client: TestClient):
    """The radio is hidden inside the button, never removed: it is what
    the form posts, what the keyboard moves between, and what `required`
    is checked on."""
    page = BeautifulSoup(client.get("/add?kind=file").text, "html.parser")
    group = page.find(class_="segmented")
    assert isinstance(group, Tag)

    for label in group.find_all("label"):
        radio = label.find("input", attrs={"type": "radio"})
        assert isinstance(radio, Tag)
        assert radio.has_attr("required")
        assert not radio.has_attr("checked"), "#431: nothing is chosen for the reader"


def test_a_preference_dropdown_is_named_by_its_label_and_marked_for_the_script(
    client: TestClient,
):
    page = BeautifulSoup(client.get("/settings").text, "html.parser")

    for name in ("theme", "face", "size", "spacing", "width", "strength", "labels"):
        select = page.find("select", attrs={"name": name})
        assert isinstance(select, Tag), name
        assert select.has_attr("data-pref"), name
        label = page.find("label", attrs={"for": select.get("id")})
        assert isinstance(label, Tag) and label.get_text(strip=True), name


# ---------------------------------------------------------------------------
# Every input is drawn
# ---------------------------------------------------------------------------


def rule_for(css: str, selector: str) -> str:
    """The declarations of the one rule whose whole selector is `selector`."""
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = [
        body
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", code)
        if head.strip() == selector
    ]
    assert len(found) == 1, (selector, len(found))
    return found[0]


def test_a_radio_and_a_checkbox_are_drawn_rather_than_the_browsers(
    client: TestClient,
):
    css = client.get("/static/kennis.css").text

    both = rule_for(css, 'input[type="radio"],\ninput[type="checkbox"]')
    assert "appearance: none" in both
    assert "border-radius: 50%" in rule_for(css, 'input[type="radio"]')
    assert "var(--brand)" in rule_for(css, 'input[type="radio"]:checked')
    assert "scale(1)" in rule_for(css, 'input[type="radio"]:checked::before')
    assert "clip-path: polygon(" in rule_for(css, 'input[type="checkbox"]::before')
    assert "var(--brand)" in rule_for(css, 'input[type="checkbox"]:checked')


def test_a_select_draws_its_own_chevron_in_the_text_colour(client: TestClient):
    css = client.get("/static/kennis.css").text

    select = rule_for(css, "select")
    assert "appearance: none" in select
    assert select.count("currentColor") >= 2
    # The search bar's selects are borderless; a `background: none` there
    # would remove the chevron with the ground.
    assert "background: none" not in rule_for(css, ".searchbox select")


def test_a_pressed_segment_is_the_checked_radios_label(client: TestClient):
    css = client.get("/static/kennis.css").text

    assert "var(--brand-wash)" in rule_for(
        css, '.segmented a[aria-current="true"],\n.segmented label:has(input:checked)'
    )
    hidden = rule_for(css, '.segmented input[type="radio"]')
    assert "opacity: 0" in hidden and "display: none" not in hidden
    assert "outline" in rule_for(css, ".segmented label:has(input:focus-visible)")
