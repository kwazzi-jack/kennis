"""The window's layout is the reader's: panes that resize, a strip that
collapses, and scrollbars drawn in the theme.

Brian, 2026-10-12: the scrollbars "do not match the theme", the strip
cannot be collapsed or seen to scroll, "we should be able to move the
size of panes". `sketches/2026-10-12-layout-sizes.md` says how. Sizes
and the strip's state are cookies the server draws onto `<html>`, as the
pane's open state already is, so the first paint is right.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.layout import SIZES
from kennis.gui.theme import stylesheet

TOKEN = "a-test-token"
STATIC = Path(__file__).resolve().parents[1] / "src/kennis/gui/static"

# Written by hand (#373): each size, its cookie, its least and most in
# pixels, and the page its handle is on.
EXPECTED_SIZES = {
    "pane-width": (160, 480, "/"),
    "inspector-width": (200, 560, "document"),
    "strip-height": (40, 800, "/"),
}


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
    source.write_text("# rivers\n\nRivers carry sediment.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def page_for(client: TestClient, where: str) -> str:
    if where == "document":
        held = Collection(root=existing_corpus().corpus_root, name="notes").contents()
        where = f"/document/notes/{held.documents[0].id}"
    answer = client.get(where)
    assert answer.status_code == 200, where
    return answer.text


def root_of(page: str) -> Tag:
    found = BeautifulSoup(page, "html.parser").find("html")
    assert isinstance(found, Tag)
    return found


def code_of(name: str) -> str:
    """A script with its comments removed, so prose cannot satisfy an
    assertion about code (#337, #373)."""
    script = (STATIC / name).read_text(encoding="utf-8")
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def css() -> str:
    return re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)


def rule(selector: str) -> str:
    """Every rule whose whole selector is `selector`, joined: `:root` has
    several, the palette's first."""
    found = re.findall("^" + re.escape(selector) + r" \{([^}]*)\}", css(), re.M)
    assert found, selector
    return "\n".join(found)


# ---------------------------------------------------------------------------
# The registry and the cookies
# ---------------------------------------------------------------------------


def test_the_sizes_are_the_ones_written_down():
    assert {name: (size.least, size.most) for name, size in SIZES.items()} == {
        name: (least, most) for name, (least, most, _) in EXPECTED_SIZES.items()
    }


@pytest.mark.parametrize("name", list(EXPECTED_SIZES))
def test_a_size_in_range_is_drawn_onto_the_root(client: TestClient, name: str):
    least, most, where = EXPECTED_SIZES[name]
    client.cookies.set(name, str((least + most) // 2))

    style = root_of(page_for(client, where)).get("style")

    assert f"--{name}: {(least + most) // 2}px" in str(style)


@pytest.mark.parametrize("value", ["1", "100000", "wide", "300px", "-5", ""])
def test_a_size_out_of_range_or_not_a_number_is_not_drawn(
    client: TestClient, value: str
):
    """Anything can be in a cookie, and this one becomes CSS."""
    client.cookies.set("pane-width", value)

    style = root_of(page_for(client, "/")).get("style")

    assert "--pane-width" not in str(style or "")


def test_with_no_cookies_no_size_is_drawn(client: TestClient):
    assert root_of(page_for(client, "/")).get("style") is None


def test_the_strip_is_open_unless_the_cookie_says_closed(client: TestClient):
    assert root_of(page_for(client, "/"))["data-strip"] == "open"
    client.cookies.set("strip", "closed")
    assert root_of(page_for(client, "/"))["data-strip"] == "closed"
    client.cookies.set("strip", "sideways")
    assert root_of(page_for(client, "/"))["data-strip"] == "open"


# ---------------------------------------------------------------------------
# The handles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(EXPECTED_SIZES))
def test_each_size_has_a_handle_the_keyboard_can_reach(client: TestClient, name: str):
    least, most, where = EXPECTED_SIZES[name]
    page = BeautifulSoup(page_for(client, where), "html.parser")
    handle = page.find(attrs={"data-resize": name})

    assert isinstance(handle, Tag), name
    assert handle.get("role") == "separator"
    assert handle.get("tabindex") == "0"
    assert handle.get("aria-valuemin") == str(least)
    assert handle.get("aria-valuemax") == str(most)
    assert handle.get("aria-orientation") == (
        "horizontal" if name == "strip-height" else "vertical"
    )
    assert handle.get("aria-label") == words.RESIZE_LABELS[name]


def test_the_sizes_are_what_the_layout_reads():
    assert "--pane: var(--pane-width)" in rule(":root")
    assert "--pane-width: 16rem" in rule(":root")
    assert "width: var(--inspector-width)" in rule(".inspector")
    assert "max-height: var(--strip-height)" in rule(".strip")


def test_a_closed_pane_or_inspector_has_no_handle_to_grab():
    code = css()

    assert re.search(
        r':root\[data-pane="closed"\] \.resize-pane \{[^}]*display: none', code
    )
    assert re.search(
        r':root\[data-inspector="closed"\] \.resize-inspector \{[^}]*display: none',
        code,
    )


def test_dragging_turns_the_shells_transition_off():
    """The grid would otherwise lag the pointer by its 0.2s transition."""
    resizing = rule(":root.resizing .shell")

    assert "transition: none" in resizing


def test_the_script_is_loaded_and_composes_nothing(client: TestClient):
    page = page_for(client, "/")
    code = code_of("resize.js")

    assert '<script defer src="/static/resize.js"></script>' in page
    assert "setPointerCapture" in code
    assert "aria-valuemin" in code and "aria-valuemax" in code
    for key in ('"ArrowLeft"', '"ArrowRight"', '"ArrowUp"', '"ArrowDown"', '"Home"'):
        assert key in code, key
    assert "dblclick" in code
    # A key steps from the size last set: the pane's width transitions,
    # and measuring it mid-way made two presses move it by one step.
    assert re.search(
        r'var from = Number\(handle\.getAttribute\("aria-valuenow"\)\)', code
    )
    assert "path=/" in code and "samesite=strict" in code
    # No sentence: every word is the server's.
    assert not re.search(r'"[A-Z][a-z]+ [a-z]+', code)


# ---------------------------------------------------------------------------
# The strip
# ---------------------------------------------------------------------------


def test_the_strip_has_a_collapse_with_both_labels_from_the_server(
    client: TestClient,
):
    text = page_for(client, "/")
    page = BeautifulSoup(text, "html.parser")
    toggle = page.find(id="strip-toggle")

    assert isinstance(toggle, Tag)
    assert toggle.get("data-show") == words.STRIP_SHOW
    assert toggle.get("data-hide") == words.STRIP_HIDE
    assert toggle.get("aria-expanded") == "true"
    assert '<script defer src="/static/strip.js"></script>' in text


def test_a_collapsed_strip_keeps_only_its_first_line():
    code = css()
    collapsed = re.search(
        r':root\[data-strip="closed"\] \.strip :is\((.*?)\) \{([^}]*)\}',
        code,
        re.S,
    )

    assert collapsed, code
    for part in (".job-lines", ".job-outcome > :not(:first-child)"):
        assert part in collapsed.group(1), part
    assert "display: none" in collapsed.group(2)


def test_a_dragged_strip_height_is_its_height_while_it_shows_a_job():
    """The walk dragged the strip up 150px and nothing moved: the size
    was only a limit, and the job's lines were shorter than it."""
    assert re.search(
        r':root\[style\*="--strip-height"\] \.strip:has\(#job:not\(:empty\)\) '
        r"\{\s*height: var\(--strip-height\);",
        css(),
    )
    # And a collapse still collapses it: the later rule, same specificity.
    code = css()
    collapsed = code.index(
        ':root[data-strip="closed"] .strip:has(#job:not(:empty)) { height: auto; }'
    )
    assert collapsed > code.index(':root[style*="--strip-height"] .strip')


def test_the_collapse_is_offered_only_when_there_is_a_job():
    assert re.search(
        r"\.strip:has\(#job:empty\) #strip-toggle \{[^}]*display: none", css()
    )


def test_the_strip_script_remembers_the_state_as_the_pane_script_does():
    code = code_of("strip.js")

    assert "dataset.strip" in code
    assert "strip=" in code and "path=/" in code and "samesite=strict" in code
    assert "dataset.show" in code and "dataset.hide" in code


# ---------------------------------------------------------------------------
# Scrollbars
# ---------------------------------------------------------------------------


def test_every_scrollbar_is_thin_and_in_the_theme():
    """Standard properties: `scrollbar-color` is inherited, and
    `scrollbar-width` is not, so it goes on every element."""
    assert re.search(r"scrollbar-color: var\(--[\w-]+\) transparent", rule(":root"))
    assert "scrollbar-width: thin" in rule("*")
