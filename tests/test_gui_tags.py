"""Tags in the window (#625, sketch 2026-11-06-tags, part t3).

A hit card and a document's inspector open a dialog that tags the passage or
the document; `/tags` lists every tag and `/tags?tag=NAME` one tag's
bookmarks first, each with its words, its link and a way to the document; the
pane lists the tags; a search is kept to a tag by `tag=` in its address. Each
test submits the form the page drew (#432).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi.testclient import TestClient

from kennis.engine.context.bundle import init_bundle
from kennis.engine.tags import Anchor, read_tags
from kennis.gui.app import build_app
from kennis.links import context_link, link_to
from test_cli_tags import PAPER_ID, SOLVING, chunk_holding, indexed_paper, run

TOKEN = "t" * 32


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return indexed_paper(tmp_path, monkeypatch)


def opened() -> TestClient:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def page_of(client: TestClient, address: str) -> BeautifulSoup:
    answer = client.get(address)
    assert answer.status_code == 200, answer.text
    return BeautifulSoup(answer.text, "html.parser")


def fields_of(form: Tag, **typed: str) -> dict[str, list[str]]:
    sent: dict[str, list[str]] = {}
    for field in form.select("input[name]"):
        name = str(field["name"])
        if field.get("type") == "checkbox" and not field.has_attr("checked"):
            continue
        sent.setdefault(name, []).append(typed.get(name, str(field.get("value", ""))))
    return sent


def tag_button_for(page: BeautifulSoup, link: str) -> str:
    """The address of the tag entry in the bookmark tab of the card whose
    link is `link` (#627)."""
    for control in page.select("li.hit .bookmark-items a[href^='/tags/add']"):
        address = str(control["href"])
        if parse_qs(urlsplit(address).query).get("link") == [link]:
            return address
    raise AssertionError(f"no hit card tags {link}")


def tagged_through(client: TestClient, address: str, names: str) -> None:
    form = page_of(client, address).select_one("form.tag")
    assert form is not None
    answer = client.post(str(form["action"]), data=fields_of(form, names=names))
    assert answer.status_code in (200, 303), answer.text


# ---------------------------------------------------------------------------
# Tagging


def test_a_hit_card_tags_its_passage_through_the_dialog_it_opens(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    client = opened()
    page = page_of(client, "/?q=gains+solved+antenna&scope=literature")

    tagged_through(
        client, tag_button_for(page, link_to(PAPER_ID, chunk)), "Calibration"
    )

    (anchor,) = read_tags(corpus / "tags.yml")["calibration"]
    assert (anchor.document, anchor.chunk) == (PAPER_ID, chunk)


def test_the_dialog_offers_the_tags_in_use(corpus: Path):
    run("tag", "to-read", PAPER_ID)
    client = opened()

    dialog = page_of(client, f"/tags/add?link={link_to(PAPER_ID, None)}")

    assert [str(option["value"]) for option in dialog.select("datalist option")] == [
        "to-read"
    ]


def test_a_name_with_a_space_is_refused_and_nothing_written(corpus: Path):
    client = opened()
    form = page_of(client, f"/tags/add?link={link_to(PAPER_ID, None)}").select_one(
        "form.tag"
    )

    answer = client.post(
        str(form["action"]),
        data=fields_of(form, names="phase calibration"),
        headers={"HX-Request": "true"},
    )

    assert "not a tag name" in answer.text
    assert not (corpus / "tags.yml").exists()


def test_a_context_hit_is_tagged_in_its_project(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains per scan here.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")
    client = opened()
    page = page_of(client, "/?q=gains+per+scan&scope=context")

    tagged_through(
        client, tag_button_for(page, context_link("pipelines", "ours.md", 0)), "mine"
    )

    assert read_tags(root / ".context" / "tags.yml")["mine"][0].document == "ours.md"
    assert not (corpus / "tags.yml").exists()


# ---------------------------------------------------------------------------
# The tags' pages


def test_the_tags_page_lists_each_tag_and_its_count(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    run("tag", "calibration", PAPER_ID)

    entry = page_of(opened(), "/tags").select_one("a[href='/tags?tag=calibration']")

    assert entry is not None
    assert "calibration" in entry.get_text()
    assert "2" in entry.get_text()


def test_a_tag_s_page_lists_bookmarks_first_with_words_link_and_way_in(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", PAPER_ID)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")

    page = page_of(opened(), "/tags?tag=calibration")
    items = page.select("li.tagged")

    assert [item["data-kind"] for item in items] == ["passage", "document"]
    bookmark = items[0]
    assert "The gains were solved" in bookmark.get_text()
    assert link_to(PAPER_ID, chunk) in bookmark.get_text()
    way_in = bookmark.select_one("a.title")
    assert way_in is not None
    assert str(way_in["href"]).startswith(
        f"/document/literature/{PAPER_ID}?chunk={chunk}"
    )


def test_a_tag_s_page_searches_within_the_tag(corpus: Path):
    run("tag", "calibration", PAPER_ID)

    page = page_of(opened(), "/tags?tag=calibration")

    assert page.select_one("a[href='/?tag=calibration']") is not None


def test_removing_on_the_tag_page_untags(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("li.tagged form.untag")
    assert form is not None

    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    assert read_tags(corpus / "tags.yml") == {}


def test_a_detached_bookmark_says_so_and_can_still_be_removed(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").split("## 2.2")[0], encoding="utf-8"
    )
    run("corpus", "index")
    client = opened()
    item = page_of(client, "/tags?tag=calibration").select_one("li.tagged")
    assert item is not None
    assert item["data-state"] == "detached"
    assert "detached" in item.get_text()
    form = item.select_one("form.untag")

    client.post(str(form["action"]), data=fields_of(form))

    assert read_tags(corpus / "tags.yml") == {}


def test_the_pane_lists_the_tags(corpus: Path):
    run("tag", "calibration", PAPER_ID)

    pane = page_of(opened(), "/corpus").select_one("nav.pane")

    entry = pane.select_one("a[href='/tags?tag=calibration']")
    assert entry is not None
    assert "1" in entry.get_text()


# ---------------------------------------------------------------------------
# Searching


@pytest.fixture
def with_a_note(corpus: Path, tmp_path: Path) -> Path:
    source = tmp_path / "drift.md"
    source.write_text("# Drift\n\nThe gains drift between scans.\n", encoding="utf-8")
    run("corpus", "add", "-n", str(source))
    run("corpus", "index")
    return corpus


def test_a_search_is_kept_to_a_tag_by_its_address(with_a_note: Path):
    run("tag", "calibration", PAPER_ID)
    client = opened()

    page = page_of(client, "/?q=gains&tag=calibration")

    collections = {str(item["data-collection"]) for item in page.select("li.hit")}
    assert collections == {"literature"}
    kept = page.select("form.searchbox input[type=hidden][name=tag]")
    assert [str(field["value"]) for field in kept] == ["calibration"]


def test_the_results_push_an_address_that_keeps_the_tag(with_a_note: Path):
    run("tag", "calibration", PAPER_ID)

    answer = opened().get("/hits", params={"q": "gains", "tag": "calibration"})

    assert "tag=calibration" in answer.headers["HX-Push-Url"]


def test_a_tag_nothing_carries_is_said_above_the_results(with_a_note: Path):
    page = page_of(opened(), "/?q=gains&tag=nowhere")

    assert "nothing is tagged nowhere" in page.get_text()


# ---------------------------------------------------------------------------
# The document's inspector


def test_the_inspector_lists_the_document_s_tags_and_tags_it_whole(corpus: Path):
    chunk = chunk_holding(corpus, SOLVING)
    run("tag", "calibration", f"id={PAPER_ID}", f"chunk={chunk}")
    client = opened()
    page = page_of(client, f"/document/literature/{PAPER_ID}")
    tags = page.select_one("aside.inspector details.tags")
    assert tags is not None
    assert "calibration" in tags.get_text()
    control = tags.select_one("a.tag-document")
    assert control is not None

    tagged_through(client, str(control["href"]), "to-read")

    assert read_tags(corpus / "tags.yml")["to-read"] == (Anchor(PAPER_ID),)


def test_removing_in_the_inspector_returns_to_the_document(corpus: Path):
    run("tag", "calibration", PAPER_ID)
    client = opened()
    address = f"/document/literature/{PAPER_ID}"
    form = page_of(client, address).select_one("details.tags form.untag")
    assert form is not None

    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    assert answer.headers["location"] == address
    assert read_tags(corpus / "tags.yml") == {}


@pytest.mark.parametrize("elsewhere", ["//example.com/", "https://example.com/", ""])
def test_a_remove_never_returns_outside_the_window(corpus: Path, elsewhere: str):
    run("tag", "calibration", PAPER_ID)
    client = opened()
    form = page_of(client, "/tags?tag=calibration").select_one("form.untag")
    sent = fields_of(form)
    sent["back"] = [elsewhere]

    answer = client.post(str(form["action"]), data=sent)

    assert answer.headers["location"] == "/tags?tag=calibration"
