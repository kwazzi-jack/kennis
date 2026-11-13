"""The settings page in tabs (#670): each tab its own address, the save
button in a bar that stays in view, and chips for a setting that is an
ordered list.

What each tab holds is written here by hand. Compared with the table the
page is drawn from, moving a heading to another tab would move it in both
and every test would pass (#373).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.settings import config_path
from kennis.engine.setup import apply_answers
from kennis.gui.app import build_app
from test_gui_kennis_settings import EXPECTED_GROUPS, EXPECTED_ROWS

TOKEN = "a-test-token"
ORDER_KEY = "retrieval.default_collections"

# name, label, address.
EXPECTED_TABS = [
    ("window", "Window", "/settings"),
    ("searching", "Searching", "/settings?tab=searching"),
    ("documents", "Documents", "/settings?tab=documents"),
    ("system", "System", "/settings?tab=system"),
    ("backup", "Backup", "/settings?tab=backup"),
]
ADDRESS = {name: address for name, _, address in EXPECTED_TABS}
# The headings of kennis's configuration, by the tab each is on.
EXPECTED_HEADINGS = {
    "searching": ["Searching and indexing"],
    "documents": [
        "Converting documents",
        "Adding documents",
        "Citing passages",
        "Reading documents",
    ],
    "system": ["Command line", "Log file", "Background service"],
}
# Which part of the page a tab draws, by its `data-section`.
EXPECTED_SECTION = {
    "window": "window",
    "searching": "kennis",
    "documents": "kennis",
    "system": "kennis",
    "backup": "backup",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def page_of(client: TestClient, tab: str) -> BeautifulSoup:
    answered = client.get(ADDRESS[tab])
    assert answered.status_code == 200, answered.text[:300]
    return BeautifulSoup(answered.text, "html.parser")


def tabs_of(page: BeautifulSoup | Tag) -> list[Tag]:
    return list(page.select("nav.settings-tabs a.settings-tab"))


def rows_of(page: BeautifulSoup | Tag) -> list[str]:
    return [str(row["data-key"]) for row in page.select(".setting[data-key]")]


def kennis_form(page: BeautifulSoup | Tag) -> Tag:
    form = page.select_one("form.kennis-settings")
    assert isinstance(form, Tag)
    return form


def as_drawn(form: Tag, **changes: str) -> dict[str, str]:
    """What submitting the drawn form sends: every named control with the
    value it holds, a ticked box's `true` after its hidden `false`."""
    sent: dict[str, str] = {}
    for control in form.select("input[name], select[name]"):
        name = str(control["name"])
        if control.has_attr("disabled"):
            continue
        if control.name == "select":
            chosen = control.select_one("option[selected]")
            sent[name] = str(chosen["value"]) if chosen else ""
        elif control.get("type") == "checkbox":
            if control.has_attr("checked"):
                sent[name] = str(control["value"])
        else:
            sent[name] = str(control.get("value", ""))
    return {**sent, **changes}


def saved() -> dict[str, dict[str, object]]:
    return tomllib.loads(config_path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The tabs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tab", [name for name, _, _ in EXPECTED_TABS])
def test_every_tab_draws_the_same_row_of_tabs_and_marks_itself(
    client: TestClient, tab: str
):
    drawn = tabs_of(page_of(client, tab))

    assert [(link.get_text(strip=True), str(link["href"])) for link in drawn] == [
        (label, address) for _, label, address in EXPECTED_TABS
    ]
    current = [link for link in drawn if link.get("aria-current") == "page"]
    assert [str(link["href"]) for link in current] == [ADDRESS[tab]]
    # A button with an icon, never a line of link text (Brian, 2026-10).
    assert all(link.find("svg") is not None for link in drawn)


@pytest.mark.parametrize("tab", [name for name, _, _ in EXPECTED_TABS])
def test_a_tab_draws_its_own_part_and_no_other(client: TestClient, tab: str):
    page = page_of(client, tab)

    drawn = [str(found["data-section"]) for found in page.select("[data-section]")]
    assert drawn == [EXPECTED_SECTION[tab]]


@pytest.mark.parametrize("tab", list(EXPECTED_HEADINGS))
def test_a_tab_holds_the_headings_written_for_it(client: TestClient, tab: str):
    page = page_of(client, tab)

    headings = [
        found.get_text(strip=True) for found in page.select(".setting-group h3")
    ]
    assert headings == EXPECTED_HEADINGS[tab]
    assert rows_of(page) == [
        key for heading in EXPECTED_HEADINGS[tab] for key in EXPECTED_GROUPS[heading]
    ]


def test_every_setting_is_on_exactly_one_tab(client: TestClient):
    drawn = [key for tab in EXPECTED_HEADINGS for key in rows_of(page_of(client, tab))]

    assert sorted(drawn) == sorted(EXPECTED_ROWS)
    assert set(EXPECTED_GROUPS) == {
        heading for headings in EXPECTED_HEADINGS.values() for heading in headings
    }, "a heading of the configuration is written for no tab"


def test_settings_alone_is_the_window_tab(client: TestClient):
    page = BeautifulSoup(client.get("/settings").text, "html.parser")

    assert page.select_one("[data-section=window]") is not None


def test_a_tab_there_is_not_answers_with_the_first(client: TestClient):
    answered = client.get("/settings", params={"tab": "nonsense"})

    assert answered.status_code == 303
    assert answered.headers["location"] == "/settings"


# ---------------------------------------------------------------------------
# Saving a tab
# ---------------------------------------------------------------------------


def test_saving_a_tab_writes_its_fields_and_leaves_the_other_tabs_alone(
    client: TestClient,
):
    apply_answers({"retrieval.default_top_k": "7", "logging.backup_count": "9"})
    form = kennis_form(page_of(client, "documents"))
    assert "retrieval.default_top_k" not in as_drawn(form), (
        "the documents tab draws a searching field, so this proves nothing"
    )

    answered = client.post(
        str(form["action"]),
        data=as_drawn(form, **{"corpus.default_group": "inbox"}),
        headers={"HX-Request": "true"},
    )

    assert answered.status_code == 200, answered.text[:300]
    written = saved()
    assert written["corpus"]["default_group"] == "inbox"
    assert written["retrieval"]["default_top_k"] == 7
    assert written["logging"]["backup_count"] == 9


def test_a_saved_tab_is_answered_with_that_tab(client: TestClient):
    form = kennis_form(page_of(client, "documents"))
    before = rows_of(form)

    answered = client.post(
        str(form["action"]),
        data=as_drawn(form, **{"corpus.default_group": "inbox"}),
        headers={"HX-Request": "true"},
    )

    section = BeautifulSoup(answered.text, "html.parser")
    assert rows_of(section) == before
    assert as_drawn(kennis_form(section))["tab"] == "documents"


def test_without_a_script_a_saved_tab_is_that_tab_s_page(client: TestClient):
    form = kennis_form(page_of(client, "system"))

    answered = client.post(
        str(form["action"]), data=as_drawn(form, **{"logging.backup_count": "4"})
    )

    page = BeautifulSoup(answered.text, "html.parser")
    current = [link for link in tabs_of(page) if link.get("aria-current") == "page"]
    assert [str(link["href"]) for link in current] == [ADDRESS["system"]]
    assert saved()["logging"]["backup_count"] == 4


def test_a_redraw_keeps_its_tab(client: TestClient):
    """On a tab that is not the first: a redraw that forgot its tab would
    draw the first one's rows, which on the first tab is the right answer."""
    form = kennis_form(page_of(client, "documents"))
    choice = form.select_one("select[hx-get]")
    assert isinstance(choice, Tag)
    drawn = as_drawn(form)
    sent = {
        str(field["name"]): drawn[str(field["name"])]
        for field in form.select("[data-redraw][name]")
        if str(field["name"]) in drawn
    }
    assert sent.get("tab") == "documents", "the redraw does not say which tab"

    answered = client.get(
        str(choice["hx-get"]), params=sent, headers={"HX-Request": "true"}
    )

    section = BeautifulSoup(answered.text, "html.parser")
    assert "corpus.default_group" in rows_of(section)
    assert "embedding.backend" not in rows_of(section)


def test_a_rebuild_s_undo_and_later_stay_on_the_tab(client: TestClient):
    form = kennis_form(page_of(client, "searching"))

    answered = client.post(
        str(form["action"]),
        data=as_drawn(form, **{"chunking.size": "900"}),
        headers={"HX-Request": "true"},
    )

    section = BeautifulSoup(answered.text, "html.parser")
    undo = section.select_one("form.undo")
    assert isinstance(undo, Tag), "changing the passage size offers no rebuild"
    assert as_drawn(undo)["tab"] == "searching"
    later = section.select_one("a[data-later]")
    assert isinstance(later, Tag)
    assert str(later["href"]) == ADDRESS["searching"]
    assert "tab=searching" in str(later["hx-get"])


# ---------------------------------------------------------------------------
# The save bar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tab", list(EXPECTED_HEADINGS))
def test_the_save_button_is_the_bar_s_primary_action(client: TestClient, tab: str):
    form = kennis_form(page_of(client, tab))

    (button,) = form.select("button[type=submit]")
    assert button.find_parent(class_="save-bar") is not None
    assert "primary" in button.get("class", [])
    assert button.find("svg") is not None
    assert button.get_text(strip=True) == "Save settings"


def test_what_a_save_came_to_is_said_beside_the_button(client: TestClient):
    form = kennis_form(page_of(client, "documents"))

    answered = client.post(
        str(form["action"]),
        data=as_drawn(form, **{"corpus.default_group": "inbox"}),
        headers={"HX-Request": "true"},
    )

    section = BeautifulSoup(answered.text, "html.parser")
    (outcome,) = section.select(".outcome")
    assert outcome.get_text(strip=True) == "Saved."
    assert outcome.find_parent(class_="save-bar") is not None
    assert outcome.get("role") == "status"


def test_a_refusal_is_said_beside_the_button_and_beside_its_field(
    client: TestClient,
):
    form = kennis_form(page_of(client, "searching"))

    answered = client.post(
        str(form["action"]),
        data=as_drawn(form, **{ORDER_KEY: "notes papers"}),
        headers={"HX-Request": "true"},
    )

    section = BeautifulSoup(answered.text, "html.parser")
    (outcome,) = section.select(".save-bar .outcome")
    assert "role-error" in outcome.get("class", [])
    row = section.select_one(f'.setting[data-key="{ORDER_KEY}"]')
    assert isinstance(row, Tag)
    assert "papers" in row.select_one(".role-error").get_text()
    assert not config_path().is_file(), "a refused save wrote the file"


def test_the_backup_tab_s_action_is_primary(client: TestClient):
    page = page_of(client, "backup")

    primary = [
        button.get_text(strip=True)
        for button in page.select("[data-section=backup] button.primary")
    ]
    assert primary == ["Back up now"]


# ---------------------------------------------------------------------------
# Chips for the default collections
# ---------------------------------------------------------------------------


def order_row(client: TestClient) -> Tag:
    row = page_of(client, "searching").select_one(f'.setting[data-key="{ORDER_KEY}"]')
    assert isinstance(row, Tag)
    return row


def test_the_field_is_what_posts_and_the_chips_wait_for_a_script(
    client: TestClient,
):
    """Without a script the row is its text field, as every setting is. The
    chips are drawn hidden and `order.js` trades the two."""
    row = order_row(client)

    (field,) = row.select(f'input[name="{ORDER_KEY}"]')
    assert field.get("type") == "text"
    assert field.get("value") == "context literature docs notes"
    assert not field.has_attr("hidden")
    (chips,) = row.select("ol.order-chips")
    assert chips.has_attr("hidden")
    assert chips["data-order-for"] == field["id"]


def test_the_chips_are_every_collection_listed_first_in_the_order_set(
    client: TestClient,
):
    apply_answers({ORDER_KEY: "notes docs"})

    chips = order_row(client).select("ol.order-chips > li.order-chip")

    assert [str(chip["data-value"]) for chip in chips] == [
        "notes",
        "docs",
        "context",
        "literature",
    ]
    ticked = [
        chip.select_one("input[type=checkbox]").has_attr("checked") for chip in chips
    ]
    assert ticked == [True, True, False, False]
    assert [chip.has_attr("data-left-out") for chip in chips] == [
        False,
        False,
        True,
        True,
    ]


def test_a_chip_can_be_moved_and_left_out_from_the_keyboard(client: TestClient):
    """Dragging is the mouse's way; each chip also has a button either way
    and a tick box, each named for a screen reader with its collection."""
    for chip in order_row(client).select("li.order-chip"):
        name = str(chip["data-value"])
        assert chip.get("draggable") == "true"
        moves = {
            str(button["data-move"]): str(button["aria-label"])
            for button in chip.select("button[type=button][data-move]")
        }
        assert set(moves) == {"earlier", "later"}
        assert all(name in label for label in moves.values())
        assert moves["earlier"] != moves["later"]
        box = chip.select_one("input[type=checkbox]")
        assert isinstance(box, Tag)
        # Not a field of the form: the text field is what posts.
        assert not box.has_attr("name")
        assert name in str(box["aria-label"])
        assert chip.find("svg") is not None


def test_the_script_is_served_and_asked_for_where_the_chips_are(client: TestClient):
    assert client.get("/static/order.js").status_code == 200
    searching = page_of(client, "searching")
    assert searching.select('script[src="/static/order.js"]')
    assert not page_of(client, "window").select('script[src="/static/order.js"]')


def test_the_script_composes_no_words(client: TestClient):
    """Every word on the page is the server's (`gui/CLAUDE.md`)."""
    script = client.get("/static/order.js").text
    code = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )

    for word in ("Move ", "Include", "Drag", "left out", "Untick"):
        assert word not in code, word
