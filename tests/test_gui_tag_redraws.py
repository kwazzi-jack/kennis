"""A tag added in the window shows where it was put, at once (#49).

The dialog's answer names the parts of the page that show tags, by the
hidden hooks every answer that changes another part of the page carries
(#457). These tests read the hooks from the answer and the elements from
the page the dialog was opened on, and assert the two meet: a hook naming
an id no page draws would redraw nothing, and pass any test that checked
the answer alone.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi.testclient import TestClient

from kennis.links import link_to
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper
from test_gui_tags import fields_of, opened, page_of, tag_button_for

SEARCH = "/?q=gains+solved+antenna&scope=literature"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def hooks_of(answer: str) -> list[Tag]:
    return list(BeautifulSoup(answer, "html.parser").select("[data-redraw-id]"))


def tagged_from(
    client: TestClient, page_address: str, dialog_address: str, names: str
) -> str:
    """Tag through the dialog as the page would: from htmx, with the page's
    own address as htmx sends it."""
    form = page_of(client, dialog_address).select_one("form.tag")
    assert form is not None
    answer = client.post(
        str(form["action"]),
        data=fields_of(form, names=names),
        headers={**HTMX, "HX-Current-URL": f"http://127.0.0.1:8123{page_address}"},
    )
    assert answer.status_code == 200, answer.text
    return answer.text


def test_a_card_s_chips_are_redrawn_from_its_own_page(corpus: Path):
    link = link_to(PAPER_ID, chunk_holding(corpus, SOLVING))
    client = opened()
    page = page_of(client, SEARCH)
    dialog = tag_button_for(page, link)

    answer = tagged_from(client, SEARCH, dialog, "calibration")

    by_id = {str(hook["data-redraw-id"]): hook for hook in hooks_of(answer)}
    (card,) = [
        str(chips["id"])
        for item in page.select("li.hit")
        if item.select_one(f'a[href="{dialog}"]') is not None
        for chips in item.select(".hit-tags[id]")
    ]
    assert card in by_id, "the answer names no element the card draws"
    hook = by_id[card]
    assert hook["data-redraw-route"] == SEARCH
    assert hook["data-redraw-select"] == f"#{card}"
    # What the route answers holds that element, with the tag on it.
    redrawn = page_of(client, str(hook["data-redraw-route"])).select_one(
        str(hook["data-redraw-select"])
    )
    assert redrawn is not None
    assert [chip.get_text(strip=True) for chip in redrawn.select(".tag-chip")] == [
        "calibration"
    ]
    assert not redrawn.has_attr("hidden")


def test_an_untagged_card_draws_its_chips_paragraph_hidden(corpus: Path):
    """Always drawn, so a redraw has an element to replace."""
    page = page_of(opened(), SEARCH)

    for card in page.select("li.hit"):
        (chips,) = card.select(".hit-tags[id]")
        assert chips.has_attr("hidden")
        assert chips.select(".tag-chip") == []


def test_two_cards_never_share_an_id(corpus: Path):
    # A word from each of the paper's three sections.
    page = page_of(opened(), "/?q=measurement+visibilities+gains&scope=literature")

    drawn = [str(chips["id"]) for chips in page.select(".hit-tags[id]")]
    assert len(drawn) >= 2, "the fixture no longer finds two passages"
    assert len(set(drawn)) == len(drawn)


def test_a_document_s_tags_are_redrawn_from_its_own_page(corpus: Path):
    client = opened()
    address = f"/document/literature/{PAPER_ID}"
    page = page_of(client, address)
    tag_this = page.select_one("a.tag-document")
    assert tag_this is not None

    answer = tagged_from(client, address, str(tag_this["href"]), "to-read")

    (section,) = page.select("details.tags[id]")
    by_id = {str(hook["data-redraw-id"]): hook for hook in hooks_of(answer)}
    hook = by_id[str(section["id"])]
    assert hook["data-redraw-route"] == address
    redrawn = page_of(client, address).select_one(str(hook["data-redraw-select"]))
    assert redrawn is not None
    assert "to-read" in [
        chip.get_text(strip=True) for chip in redrawn.select(".tag-chip")
    ]


@pytest.mark.parametrize(
    "current",
    ["https://elsewhere.example//evil.example/x", "javascript:alert(1)", ""],
)
def test_a_page_address_that_is_not_this_window_s_is_not_asked_again(
    corpus: Path, current: str
):
    client = opened()
    dialog = f"/tags/add?link={link_to(PAPER_ID, None)}"
    form = page_of(client, dialog).select_one("form.tag")
    assert form is not None

    answer = client.post(
        str(form["action"]),
        data=fields_of(form, names="to-read"),
        headers={**HTMX, "HX-Current-URL": current},
    )

    for hook in hooks_of(answer.text):
        route = str(hook["data-redraw-route"])
        assert route.startswith("/") and not route.startswith("//"), route
        assert not urlsplit(route).netloc


def test_nothing_changed_asks_for_no_redraw(corpus: Path):
    client = opened()
    dialog = f"/tags/add?link={link_to(PAPER_ID, None)}"
    tagged_from(client, SEARCH, dialog, "to-read")

    again = tagged_from(client, SEARCH, dialog, "to-read")

    assert hooks_of(again) == []


def test_the_script_takes_only_the_named_element():
    from test_gui_feedback import code_of

    code = code_of("redraws.js")
    assert ".select = hook.dataset.redrawSelect" in code
