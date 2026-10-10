"""Unit 11g: the palette.

One list of every action and place, actions first, each with its kind,
filtered as it is typed and run with Enter. Every entry is an alias of a
route that already exists, so nothing is reachable only through it - and
without a script the palette is a page of those links.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"

# Written by hand (#373): every entry, in order, as (label, address, kind).
EXPECTED_ENTRIES = [
    ("Add a paper", "/add?kind=paper", "action"),
    ("Add a documentation site", "/add?kind=site", "action"),
    ("Add a file", "/add?kind=file", "action"),
    ("Add several by group", "/add?kind=group", "action"),
    ("Write a note", "/remember", "action"),
    ("Index every collection", "/index", "action"),
    ("Index literature", "/index?collection=literature", "action"),
    ("Index docs", "/index?collection=docs", "action"),
    ("Index notes", "/index?collection=notes", "action"),
    ("Synchronise", "/sync", "action"),
    ("Install a pack", "/pack", "action"),
    ("literature", "/collection/literature", "collection"),
    ("docs", "/collection/docs", "collection"),
    ("notes", "/collection/notes", "collection"),
    ("Corpus", "/corpus", "page"),
    ("Recent searches", "/", "page"),
    ("Activity", "/activity", "page"),
]

# And which role each kind wears, so the list is not grey.
EXPECTED_ROLES = {"action": "command", "collection": "operation", "page": "value"}


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    return build_app(TOKEN)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    opened = TestClient(app, follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def palette_of(client: TestClient, headers: dict[str, str] | None = None) -> Tag:
    answer = client.get("/palette", headers=headers or HTMX)
    assert answer.status_code == 200
    page = BeautifulSoup(answer.text, "html.parser")
    listbox = page.find(attrs={"role": "listbox"})
    assert isinstance(listbox, Tag), answer.text
    return listbox


def options_of(listbox: Tag) -> list[Tag]:
    return [option for option in listbox.find_all(attrs={"role": "option"})]


def entry_of(option: Tag) -> tuple[str, str, str]:
    link = option.find("a")
    kind = option.find(class_="kind")
    label = option.find(class_="label")
    assert isinstance(link, Tag) and isinstance(kind, Tag) and isinstance(label, Tag)
    return label.get_text(strip=True), str(link["href"]), kind.get_text(strip=True)


def classes(element: Tag) -> list[str]:
    found = element.get("class") or []
    return list(found) if isinstance(found, list) else found.split()


def code_of(name: str) -> str:
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------


def test_the_palette_lists_every_action_and_place_in_order(client: TestClient):
    entries = [entry_of(option) for option in options_of(palette_of(client))]

    assert entries == EXPECTED_ENTRIES


def test_actions_come_first(client: TestClient):
    kinds = [entry_of(option)[2] for option in options_of(palette_of(client))]
    last_action = max(n for n, kind in enumerate(kinds) if kind == "action")

    assert all(kind == "action" for kind in kinds[: last_action + 1])


@pytest.mark.parametrize(("label", "address", "kind"), EXPECTED_ENTRIES)
def test_every_entry_is_a_route_that_answers(
    client: TestClient, label: str, address: str, kind: str
):
    """An alias, never the only way in: each address answers as a page
    without a script and, for an action, as a dialog with one."""
    assert client.get(address).status_code == 200
    if kind == "action":
        dialog = client.get(address, headers=HTMX).text
        assert dialog.lstrip().startswith("<dialog") or "<dialog" in dialog[:400]


def test_an_action_opens_its_dialog_and_a_place_navigates(client: TestClient):
    for option in options_of(palette_of(client)):
        link = option.find("a")
        assert isinstance(link, Tag)
        _, address, kind = entry_of(option)
        if kind == "action":
            assert link.get("hx-get") == address
            assert link.get("hx-target") == "#dialog"
        else:
            assert link.get("hx-get") is None, address


def test_each_kind_wears_its_role(client: TestClient):
    for option in options_of(palette_of(client)):
        kind = option.find(class_="kind")
        assert isinstance(kind, Tag)
        role = EXPECTED_ROLES[kind.get_text(strip=True)]
        assert f"role-{role}" in classes(kind)
        icon = option.find("svg")
        assert isinstance(icon, Tag)
        assert option.find(class_=f"role-{role}") is not None


def test_the_label_stays_ink(client: TestClient):
    for option in options_of(palette_of(client)):
        label = option.find(class_="label")
        assert isinstance(label, Tag)
        assert not any(name.startswith("role-") for name in classes(label))


def test_each_entry_carries_what_it_is_matched_on(client: TestClient):
    """The server lower-cases label and kind, so the script compares and
    composes nothing."""
    for option in options_of(palette_of(client)):
        label, _, kind = entry_of(option)
        assert option["data-match"] == f"{label} {kind}".casefold()


def test_the_first_entry_starts_selected(client: TestClient):
    options = options_of(palette_of(client))

    assert options[0]["aria-selected"] == "true"
    assert all(option["aria-selected"] == "false" for option in options[1:])
    assert all(option.get("id") for option in options)


def test_the_input_is_a_combobox_over_the_list(client: TestClient):
    page = BeautifulSoup(client.get("/palette", headers=HTMX).text, "html.parser")
    field = page.find("input", attrs={"role": "combobox"})
    listbox = page.find(attrs={"role": "listbox"})

    assert isinstance(field, Tag) and isinstance(listbox, Tag)
    assert field["aria-controls"] == listbox["id"]
    assert field["aria-label"] == words.PALETTE_PROMPT


def test_nothing_matches_is_the_servers_sentence(client: TestClient):
    page = BeautifulSoup(client.get("/palette", headers=HTMX).text, "html.parser")
    empty = page.find(class_="palette-empty")

    assert isinstance(empty, Tag)
    assert empty.get_text(strip=True) == words.PALETTE_EMPTY
    assert empty.has_attr("hidden")


def test_without_a_script_it_is_a_page_of_links(client: TestClient):
    page = client.get("/palette")

    assert 'class="shell"' in page.text
    assert [entry_of(option) for option in options_of(palette_of(client, {}))] == (
        EXPECTED_ENTRIES
    )


# ---------------------------------------------------------------------------
# Reaching it
# ---------------------------------------------------------------------------


def test_the_bar_opens_the_palette_without_being_one_of_its_actions(client: TestClient):
    page = BeautifulSoup(client.get("/").text, "html.parser")
    bar = page.find("header", class_="bar")
    assert isinstance(bar, Tag)
    link = bar.find("a", class_="palette-open")

    assert isinstance(link, Tag)
    assert link["href"] == "/palette"
    assert link["hx-get"] == "/palette"
    assert link["hx-target"] == "#dialog"
    assert "action" not in classes(link)
    assert link["aria-label"] == words.PALETTE_TITLE
    assert words.PALETTE_SHORTCUT in link.get_text()


def test_the_index_form_checks_the_collection_it_was_opened_on(client: TestClient):
    page = BeautifulSoup(
        client.get("/index?collection=notes", headers=HTMX).text, "html.parser"
    )
    checked = page.find_all("input", attrs={"name": "collection", "checked": True})

    assert [radio["value"] for radio in checked] == ["notes"]


def test_the_index_form_checks_every_collection_by_default(client: TestClient):
    for address in ("/index", "/index?collection=elsewhere"):
        page = BeautifulSoup(client.get(address, headers=HTMX).text, "html.parser")
        checked = page.find_all("input", attrs={"name": "collection", "checked": True})
        assert [radio["value"] for radio in checked] == [""], address


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------


def test_the_script_is_loaded_and_composes_no_words(client: TestClient):
    code = code_of("palette.js")

    assert '<script defer src="/static/palette.js"></script>' in client.get("/").text
    assert not re.search(r"\"[A-Za-z]+ [A-Za-z ]+\"", code)


def test_the_script_wraps_keeps_the_selection_in_view_and_runs_on_enter():
    code = code_of("palette.js")

    for needed in (
        '"ArrowDown"',
        '"ArrowUp"',
        '"Enter"',
        "scrollIntoView",
        "aria-activedescendant",
    ):
        assert needed in code, needed
    # Wrapping is modular arithmetic over the visible entries.
    assert re.search(r"%\s*visible\.length", code)


def test_ctrl_k_opens_the_palette_through_the_bar(client: TestClient):
    code = code_of("palette.js")

    assert re.search(r'event\.key\.toLowerCase\(\) [!=]== "k"', code)
    assert "ctrlKey" in code and "metaKey" in code
    assert ".palette-open" in code


def test_the_three_kinds_wear_three_colours():
    """`option` and `command` are both cyan, so pages and actions once
    looked alike; found by measuring the page, not by reading it. The
    palette tests hold distinct names apart by dE >= 20 in both themes."""
    from kennis.gui.pages import PALETTE_ROLES
    from kennis.render.theme import ROLES

    colours = [ROLES[role].colour for role in PALETTE_ROLES.values()]

    assert None not in colours
    assert len(set(colours)) == len(colours)
