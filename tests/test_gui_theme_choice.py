"""Choosing the colours: system, light or dark.

Before this the reader had no say. `stylesheet()` emitted the light
palette at `:root` and the dark one inside
`@media (prefers-color-scheme: dark)`, so the operating system
decided and nothing could override it.

**The guard is the load-bearing part.** An explicit `light` has to
survive a dark system, and the media query is both later in the
sheet and applies to the same `:root`. Without
`:not([data-theme="light"])` on it, choosing light would appear to
do nothing on exactly the machines where a reader would want to.

**`system` has no rule.** It is the absence of the attribute
matching either of the other two, so the default is the behaviour
that existed before and a reader who never touches the control sees
no change at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.theme import DARK_GROUND, stylesheet

TOKEN = "a-test-token"
STATIC = Path(__file__).resolve().parents[1] / "src/kennis/gui/static"


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(TOKEN), follow_redirects=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def admitted(app_client: TestClient) -> TestClient:
    assert app_client.get("/", params={"token": TOKEN}).status_code == 200
    return app_client


def code_of(name: str) -> str:
    """A script without its comment lines. Concern #373: two tests
    passed against code that had lost what they asserted, because
    the sentence explaining it was still in the comment above."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------


def test_an_explicit_light_survives_a_dark_system():
    """The whole reason the guard exists. The media query is later in
    the sheet and applies to the same `:root`, so on a dark system it
    would win and choosing light would do nothing."""
    css = stylesheet()
    inside = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*([^{]*)\{", css)

    assert inside is not None, "no dark media query"
    assert ':not([data-theme="light"])' in inside.group(1), inside.group(1)


def test_an_explicit_dark_works_on_a_light_system():
    """A rule outside the media query, or a reader on a light machine
    has no way to ask for the dark palette."""
    css = stylesheet()
    found = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', css)

    assert found is not None, "nothing answers an explicit dark choice"
    assert DARK_GROUND.lower() in found.group(1).lower()


def test_the_two_dark_blocks_are_the_same_block():
    """There are two places the dark palette is written - inside the
    media query and in the explicit rule - and they must not be able
    to differ. A reader who chose dark and a reader whose system is
    dark are looking at the same thing.

    Compared as whole bodies rather than colour by colour. The first
    version of this test iterated `CSS_COLOURS_DARK` and failed on
    `blue`, which is in the palette and worn by no role, so
    `css_variables` never emits it: the test was asserting something
    that is not true of either copy."""
    css = stylesheet()
    explicit = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', css)
    inside = re.search(
        r"@media \(prefers-color-scheme: dark\) \{\s*[^{]*\{([^}]*)\}", css
    )

    assert explicit is not None and inside is not None
    assert explicit.group(1).strip() == inside.group(1).strip()
    assert DARK_GROUND.lower() in explicit.group(1).lower()


def test_choosing_the_system_asks_for_no_rule_at_all():
    """`system` is the absence of the attribute matching either of
    the others, so the default is exactly what happened before and a
    reader who never touches the control notices nothing."""
    css = stylesheet()

    assert 'data-theme="system"' not in css


# ---------------------------------------------------------------------------
# The control
# ---------------------------------------------------------------------------


def test_the_page_offers_the_three_choices(corpus: Path, client: TestClient):
    admitted(client)

    page = client.get("/").text

    for value, label in words.THEME_CHOICES:
        assert f'value="{value}"' in page, value
        assert label in page, label


def test_the_choice_is_rendered_by_the_server_from_the_cookie(
    corpus: Path, client: TestClient
):
    """Read from `localStorage` after paint, every page would render
    in the system's colours and then repaint into the chosen ones -
    a flash of the wrong palette on every load. The sidebar's
    reasoning (concern #369's unit) and more so, because this is the
    whole page rather than one column."""
    admitted(client)
    client.cookies.set("theme", "dark")

    page = client.get("/").text

    assert 'data-theme="dark"' in page


def test_the_chosen_option_is_the_one_marked_selected(corpus: Path, client: TestClient):
    """Otherwise the control says `system` while the page is dark."""
    admitted(client)
    client.cookies.set("theme", "dark")

    page = client.get("/").text
    chosen = [
        re.search(r'value="([^"]*)"', option)
        for option in re.findall(r"<option\b[^>]*>", page)
        if " selected" in option and "data-hint" not in option
    ]

    assert [found.group(1) for found in chosen if found] == ["dark"]


def test_an_unknown_cookie_value_is_the_system(corpus: Path, client: TestClient):
    """Anything can be in a cookie, and the default is the behaviour
    that existed before there was a choice."""
    admitted(client)
    client.cookies.set("theme", "chartreuse")

    page = client.get("/").text

    assert 'data-theme="chartreuse"' not in page
    assert 'data-theme="system"' in page


def test_every_page_carries_the_choice(corpus: Path, client: TestClient):
    admitted(client)
    client.cookies.set("theme", "dark")

    for path in ("/", "/held", "/remember", "/manage"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert 'data-theme="dark"' in page.text, path


def test_the_theme_script_composes_nothing_and_scopes_its_cookie():
    code = code_of("theme.js")

    for _, label in words.THEME_CHOICES:
        assert label not in code, label
    assert "samesite=strict" in code.lower()
    assert "path=/" in code


def test_the_three_choices_are_what_they_claim_to_be():
    """The tests above compare the page against `THEME_CHOICES`, so
    they agree with each other however that changes. Concern #373:
    a third statement, written by hand, of what the list should
    hold."""
    assert [value for value, _ in words.THEME_CHOICES] == [
        "system",
        "light",
        "dark",
    ]
