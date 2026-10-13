"""Milestone 12a: the settings page, and this window's own preferences.

Each preference is a cookie the server renders onto `<html>` as a data
attribute, so the first byte is right and nothing repaints after load -
the rule the theme already followed, generalised. None of them is
kennis's configuration: the command line and the MCP server never see
them, and the page says so.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient
from starlette.requests import Request

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.preferences import PREFERENCES, preference_of
from kennis.gui.theme import STRENGTH_SCALES, stylesheet

TOKEN = "a-test-token"
STATIC = Path(__file__).resolve().parents[1] / "src/kennis/gui/static"
VENDOR = STATIC / "vendor"

# Written by hand (#373): every preference, its choices in order, and its
# default - which is what the window did before there was a choice.
EXPECTED_PREFERENCES = {
    "theme": (("system", "light", "dark"), "system"),
    "face": (("serif", "sans", "hyperlegible"), "serif"),
    "size": (("small", "normal", "large", "larger"), "normal"),
    "spacing": (("normal", "wide", "wider"), "normal"),
    # Brian, 2026-10-12: the text fits the pane unless asked otherwise;
    # the reading measure the window had until then is the last choice.
    "width": (("pane", "wide", "reading"), "reading"),
    "strength": (("bars", "words"), "bars"),
    "labels": (("icons", "words", "both"), "icons"),
    "scale": (("viridis", "cividis", "plasma", "magma", "greys"), "viridis"),
}


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


def soup(text: str) -> BeautifulSoup:
    return BeautifulSoup(text, "html.parser")


def root_of(page: str) -> Tag:
    html = soup(page).find("html")
    assert isinstance(html, Tag)
    return html


def control_of(page: str, name: str) -> Tag:
    """The settings page's control for one preference, by its name."""
    found = soup(page).find(attrs={"data-preference": name})
    assert isinstance(found, Tag), name
    return found


def offered_in(control: Tag, name: str) -> list[Tag]:
    """The options of a dropdown or the radios of a list, whichever the
    preference is drawn as (`test_gui_controls.py` says which)."""
    select = control.find("select", attrs={"name": name})
    if isinstance(select, Tag):
        return list(select.find_all("option"))
    return list(control.find_all("input", attrs={"type": "radio", "name": name}))


def is_chosen(choice: Tag) -> bool:
    return choice.has_attr("selected") or choice.has_attr("checked")


def attributes_of(cookie: str) -> dict[str, str]:
    """A `Set-Cookie` header's attributes, lower-cased, by name."""
    pairs = [part.strip().split("=", 1) for part in cookie.split(";")[1:]]
    return {pair[0].lower(): pair[1].lower() if len(pair) > 1 else "" for pair in pairs}


def code_of(name: str) -> str:
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def rules_for(sheet: str, selector: str) -> str:
    """The declarations of every rule whose selector list names `selector`."""
    found = re.findall(r"([^{}]+)\{([^{}]*)\}", sheet)
    return "\n".join(body for head, body in found if selector in head)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_preferences_are_the_ones_written_down():
    assert {
        name: (tuple(value for value, _ in preference.choices), preference.default)
        for name, preference in PREFERENCES.items()
    } == EXPECTED_PREFERENCES


def test_every_choice_has_words():
    for preference in PREFERENCES.values():
        assert preference.label and preference.sentence
        assert all(label for _, label in preference.choices)


def test_the_scales_offered_are_the_scales_drawn():
    assert EXPECTED_PREFERENCES["scale"][0] == tuple(STRENGTH_SCALES)


# ---------------------------------------------------------------------------
# Rendered by the server, from the cookie
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(EXPECTED_PREFERENCES))
def test_each_preference_is_on_the_root_from_its_cookie(client: TestClient, name: str):
    chosen = EXPECTED_PREFERENCES[name][0][-1]
    client.cookies.set(name, chosen)

    assert root_of(client.get("/").text)[f"data-{name}"] == chosen


@pytest.mark.parametrize("name", list(EXPECTED_PREFERENCES))
def test_an_unknown_value_is_the_default(client: TestClient, name: str):
    """Anything can be in a cookie."""
    client.cookies.set(name, "chartreuse")

    assert (
        root_of(client.get("/").text)[f"data-{name}"] == EXPECTED_PREFERENCES[name][1]
    )


def test_with_no_cookies_every_default_is_drawn(client: TestClient):
    root = root_of(client.get("/").text)

    for name, (_, default) in EXPECTED_PREFERENCES.items():
        assert root[f"data-{name}"] == default, name


def test_every_page_carries_them(client: TestClient):
    client.cookies.set("face", "hyperlegible")

    for path in ("/", "/corpus", "/settings", "/activity", "/add"):
        answer = client.get(path)
        assert answer.status_code == 200, path
        assert root_of(answer.text)["data-face"] == "hyperlegible", path


def test_preference_of_reads_only_what_is_offered():
    asked = Request(
        {"type": "http", "headers": [(b"cookie", b"size=larger; spacing=enormous")]}
    )

    assert preference_of(asked, "size") == "larger"
    assert preference_of(asked, "spacing") == "normal"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_bar_has_a_gear_and_no_colour_control(client: TestClient):
    bar = soup(client.get("/").text).find("header", class_="bar")
    assert isinstance(bar, Tag)
    gear = bar.find("a", class_="settings-open")

    assert isinstance(gear, Tag)
    assert gear["href"] == "/settings"
    assert gear["aria-label"] == words.SETTINGS_HEADING
    assert bar.find("select", class_="theme") is None
    assert bar.find(attrs={"name": "theme"}) is None


def test_the_page_says_these_are_this_windows_alone(client: TestClient):
    page = soup(client.get("/settings").text)
    section = page.find("section", attrs={"data-section": "window"})

    assert isinstance(section, Tag)
    assert words.WINDOW_SETTINGS_NOTE in section.get_text(" ", strip=True)


@pytest.mark.parametrize("name", list(EXPECTED_PREFERENCES))
def test_each_preference_has_a_control_with_its_choices(client: TestClient, name: str):
    control = control_of(client.get("/settings").text, name)
    offered = offered_in(control, name)

    assert [choice["value"] for choice in offered] == list(
        EXPECTED_PREFERENCES[name][0]
    )
    marked = control.select(f'[name="{name}"][data-pref]')
    assert marked and all(element.name in ("select", "input") for element in marked)


@pytest.mark.parametrize("name", list(EXPECTED_PREFERENCES))
def test_the_current_choice_is_checked(client: TestClient, name: str):
    chosen = EXPECTED_PREFERENCES[name][0][1]
    client.cookies.set(name, chosen)
    control = control_of(client.get("/settings").text, name)
    offered = offered_in(control, name)

    assert [choice["value"] for choice in offered if is_chosen(choice)] == [chosen]


def test_each_scale_shows_its_five_steps(client: TestClient):
    control = control_of(client.get("/settings").text, "scale")

    for scale in EXPECTED_PREFERENCES["scale"][0]:
        swatches = control.select(f'.swatch[data-scale="{scale}"]')
        assert [swatch["data-step"] for swatch in swatches] == ["1", "2", "3", "4", "5"]


def test_without_a_script_the_form_saves_by_posting(client: TestClient):
    page = soup(client.get("/settings").text)
    form = page.find("form", class_="preferences")

    assert isinstance(form, Tag)
    assert form["action"] == "/settings"
    assert form["method"] == "post"
    assert form.find("button", attrs={"type": "submit"}) is not None


def test_posting_sets_every_cookie_and_returns_to_the_page(client: TestClient):
    sent = {name: choices[-1] for name, (choices, _) in EXPECTED_PREFERENCES.items()}

    answer = client.post("/settings", data=sent)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/settings"
    cookies = answer.headers.get_list("set-cookie")
    for name, value in sent.items():
        cookie = next(c for c in cookies if c.startswith(f"{name}="))
        assert cookie.startswith(f"{name}={value};"), cookie
        # Parsed, not searched: `path=/settings` contains `path=/`, and a
        # cookie scoped to this page would be absent from every other.
        attributes = attributes_of(cookie)
        assert attributes["path"] == "/"
        assert attributes["samesite"] == "strict"
        assert int(attributes["max-age"]) >= 365 * 24 * 3600


def test_posting_an_unknown_value_sets_nothing_for_it(client: TestClient):
    answer = client.post("/settings", data={"face": "comic", "size": "large"})
    cookies = answer.headers.get_list("set-cookie")

    assert not any(cookie.startswith("face=") for cookie in cookies)
    assert any(cookie.startswith("size=large;") for cookie in cookies)


def test_the_saved_choice_is_drawn_afterwards(client: TestClient):
    client.post("/settings", data={"spacing": "wider"})

    assert root_of(client.get("/settings").text)["data-spacing"] == "wider"


# ---------------------------------------------------------------------------
# What each preference does, in the stylesheet
# ---------------------------------------------------------------------------


def test_each_face_sets_the_column():
    sheet = stylesheet()

    assert "var(--gutter)" in rules_for(sheet, ':root[data-face="sans"]')
    assert "Atkinson Hyperlegible" in rules_for(
        sheet, ':root[data-face="hyperlegible"]'
    )
    assert ':root[data-face="serif"]' not in sheet  # the default needs no rule


def test_the_hyperlegible_face_is_vendored_and_loaded():
    sheet = stylesheet()
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", sheet)
    atkinson = [face for face in faces if "Atkinson Hyperlegible" in face]

    assert len(atkinson) == 4
    for face in atkinson:
        source = re.search(r"url\(/static/vendor/(fonts/[^)]+)\)", face)
        assert source, face
        assert (VENDOR / source.group(1)).is_file(), source.group(1)


def test_size_scales_the_whole_interface():
    """The interface is in `rem`; the root's size moves all of it."""
    sheet = stylesheet()
    sizes = {
        name: re.search(
            r"font-size:\s*([0-9.]+)%", rules_for(sheet, f':root[data-size="{name}"]')
        )
        for name in ("small", "large", "larger")
    }

    assert all(sizes.values()), sizes
    small, large, larger = (float(found.group(1)) for found in sizes.values() if found)
    assert small < 100 < large < larger


def test_spacing_widens_in_two_steps():
    sheet = stylesheet()

    def leading(name: str) -> float:
        found = re.search(
            r"--leading:\s*([0-9.]+)", rules_for(sheet, f':root[data-spacing="{name}"]')
        )
        assert found, name
        return float(found.group(1))

    assert 1.6 < leading("wide") < leading("wider")
    assert "var(--leading)" in rules_for(sheet, ".column")


def test_the_text_is_set_at_a_reading_measure_unless_a_width_is_chosen():
    """Fitting the pane was the default for a day and set passages about
    150 characters a line; every review asked for the measure back."""
    sheet = stylesheet()
    code = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)

    assert ':root[data-width="reading"]' not in sheet  # the default needs no rule
    assert "--text: var(--measure);" in code
    assert "--frame: calc(var(--margin) + var(--gap) + var(--measure));" in code
    pane = rules_for(sheet, ':root[data-width="pane"]')
    assert "--text: none" in pane
    assert "--frame: none" in pane
    assert "--text: " in rules_for(sheet, ':root[data-width="wide"]')
    assert "max-width: var(--frame)" in rules_for(sheet, ".column")
    # Every width a reading measure set now goes through the choice.
    assert "max-width: var(--measure)" not in code
    # Six: the notice (2026-10-13) lines up with the text it is about.
    assert code.count("max-width: var(--text)") == 6


def test_words_only_hides_the_bars():
    assert "display: none" in rules_for(
        stylesheet(), ':root[data-strength="words"] .cells'
    )


def test_labels_hide_the_icon_or_the_name():
    sheet = stylesheet()

    # The name leaves the eye, not the page: with `display: none` a
    # screen reader heard a level with no measure to say what it was of.
    icons = rules_for(sheet, ':root[data-labels="icons"] .measure-name')
    assert "clip-path: inset(50%)" in icons
    assert "display: none" not in icons
    assert "display: none" in rules_for(
        sheet, ':root[data-labels="words"] .measure > .icon'
    )
    assert ':root[data-labels="both"]' not in sheet


def test_each_scale_points_the_bars_at_its_own_steps():
    sheet = stylesheet()

    for scale in STRENGTH_SCALES:
        rule = rules_for(sheet, f':root[data-scale="{scale}"]')
        for step in range(1, 6):
            assert f"--strength-{step}: var(--scale-{scale}-{step})" in rule, (
                scale,
                step,
            )


def test_every_scale_is_defined_for_both_themes():
    sheet = stylesheet()
    light = sheet[: sheet.index("@media")]
    dark = sheet[sheet.index("@media") :]

    for scale, themes in STRENGTH_SCALES.items():
        for step, colour in enumerate(themes["light"], start=1):
            assert f"--scale-{scale}-{step}: {colour};" in light
        for step, colour in enumerate(themes["dark"], start=1):
            assert f"--scale-{scale}-{step}: {colour};" in dark


def test_the_scale_rules_come_after_the_theme_blocks():
    """Same specificity as the dark block's `--strength-N`, so order is
    what lets the reader's scale win in either theme."""
    sheet = stylesheet()

    assert sheet.index(':root[data-scale="viridis"]') > sheet.rindex(
        ':root[data-theme="dark"]'
    )


def test_a_swatch_wears_its_scale_step():
    sheet = stylesheet()

    for scale in STRENGTH_SCALES:
        for step in range(1, 6):
            rule = rules_for(
                sheet, f'.swatch[data-scale="{scale}"][data-step="{step}"]'
            )
            assert f"var(--scale-{scale}-{step})" in rule


# ---------------------------------------------------------------------------
# A measure carries its name, so "words" has something to show
# ---------------------------------------------------------------------------


def test_a_measure_carries_its_name_as_text():
    template = (STATIC.parent / "templates" / "hits.html").read_text(encoding="utf-8")

    assert '<span class="measure-name">{{ measure.label }}</span>' in template


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------


def test_the_script_applies_a_change_at_once_and_composes_nothing(client: TestClient):
    code = code_of("prefs.js")

    assert '<script defer src="/static/prefs.js"></script>' in client.get("/").text
    assert "[data-pref]" in code
    assert "dataset" in code
    assert "samesite=strict" in code.lower()
    assert "; path=/;" in code
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)


def test_the_script_hides_the_save_button():
    """With a script nothing waits for Save, so a Save button would be a
    control that does nothing."""
    assert "hidden" in code_of("prefs.js")


def test_the_theme_script_is_gone():
    assert not (STATIC / "theme.js").exists()
