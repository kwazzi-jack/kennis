"""Every control a dialog offers has a name a screen reader can say.

The accessibility review of 2026-10-13 found the Note dialog's three
fields and the Pack dialog's path named by placeholders alone, and every
radio group nameless. A placeholder is gone once anything is typed and a
screen reader may not read it; a nameless radio group is read as a list
of words with no question. Read from the served dialogs, so a field
added later is held to the same rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}

# Written by hand: every dialog the bar and the palette open.
DIALOGS = [
    "/remember",
    "/pack",
    "/index",
    "/sync",
    "/add",
    "/add?kind=paper",
    "/add?kind=site",
    "/add?kind=file",
    "/add?kind=group",
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


def named(control: Tag, page: BeautifulSoup) -> bool:
    """Whether a control has a name other than its placeholder."""
    if control.get("aria-label") or control.get("aria-labelledby"):
        return True
    if control.find_parent("label") is not None:
        return True
    ident = control.get("id")
    return bool(ident) and page.find("label", attrs={"for": ident}) is not None


@pytest.mark.parametrize("route", DIALOGS)
def test_every_field_in_a_dialog_is_named(client: TestClient, route: str):
    answer = client.get(route, headers=HTMX)
    assert answer.status_code == 200
    page = BeautifulSoup(answer.text, "html.parser")

    controls = page.select(
        "input:not([type=hidden]):not([type=submit]), textarea, select"
    )
    nameless = [str(control)[:80] for control in controls if not named(control, page)]

    assert controls or route == "/sync"
    assert nameless == []


@pytest.mark.parametrize("route", DIALOGS)
def test_every_radio_group_asks_its_question(client: TestClient, route: str):
    page = BeautifulSoup(client.get(route, headers=HTMX).text, "html.parser")

    groups = page.select("[role=radiogroup]")
    nameless = [
        str(group)[:80]
        for group in groups
        if not (group.get("aria-label") or group.get("aria-labelledby"))
    ]

    assert nameless == []
    for group in groups:
        pointed = group.get("aria-labelledby")
        if pointed:
            assert page.find(id=pointed) is not None, pointed


def test_the_strip_is_not_a_live_region_that_ticks(client: TestClient):
    """`#job` held a clock updated every second inside `aria-live`, so a
    screen reader read the time out again and again. What is worth
    hearing goes to one status region the progress script writes."""
    page = BeautifulSoup(client.get("/").text, "html.parser")

    assert page.find(id="job").get("aria-live") is None
    assert page.find(id="job-status").get("role") == "status"


def test_the_reader_can_be_scrolled_from_the_keyboard(
    client: TestClient, tmp_path: Path
):
    source = tmp_path / "trees.md"
    source.write_text("# Trees\n\nBark and rings.\n", encoding="utf-8")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    corpus = BeautifulSoup(client.get("/collection/notes").text, "html.parser")
    link = corpus.select_one("a[href^='/document/notes/']")
    assert link is not None

    page = BeautifulSoup(client.get(link["href"]).text, "html.parser")
    reading = page.select_one(".reading")

    assert reading.get("tabindex") == "0"
    assert reading.get("aria-label") == page.select_one("article h1").text
