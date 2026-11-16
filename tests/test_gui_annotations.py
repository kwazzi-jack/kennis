"""Annotating a selection in the window, and changing or deleting an
annotation (#50, unit 2; sketch 2026-11-16-annotate-selection).

Each test makes the request the page's script makes from what the page drew
- the article's document fields and a block's `data-source` - and then
submits the form the dialog drew (#432).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi.testclient import TestClient

from annotating import ANNOTATIONS
from kennis.engine.annotations import read_annotations
from kennis.engine.context.bundle import init_bundle
from test_cli_tags import PAPER_ID, SOLVING, run
from test_gui_tags import corpus, fields_of, opened, page_of

__all__ = ["corpus"]

PAPER_PAGE = f"/document/literature/{PAPER_ID}"


def located(
    client: TestClient, address: str, words: str, *, before: str = ""
) -> BeautifulSoup:
    """The dialog the page's script opens for a selection of `words`, made
    inside the first block that draws them."""
    page = page_of(client, address)
    article = page.select_one("article[data-annotate-document]")
    assert article is not None
    block = next(
        (
            element
            for element in article.select("[data-source]")
            if words in " ".join(element.get_text().split())
        ),
        None,
    )
    assert block is not None, f"no block of {address} draws {words!r}"
    values = {
        "document": str(article["data-annotate-document"]),
        "first": str(block["data-source"]),
        "last": str(block["data-source"]),
        "text": words,
        "before": before,
    }
    for name in ("collection", "project"):
        if article.has_attr(f"data-annotate-{name}"):
            values[name] = str(article[f"data-annotate-{name}"])
    answer = client.post(
        "/annotate/located",
        data=values,
        headers={"HX-Request": "true", "HX-Current-URL": f"http://testserver{address}"},
    )
    assert answer.status_code == 200, answer.text
    return BeautifulSoup(answer.text, "html.parser")


def submitted(
    client: TestClient, form: Tag, page: str, **typed: str
) -> tuple[int, str, dict[str, str]]:
    """`form` posted as htmx posts it from `page`, with what was typed."""
    sent = fields_of(form, **typed)
    textarea = form.select_one("textarea[name=comment]")
    if textarea is not None:
        sent["comment"] = [typed.get("comment", textarea.get_text())]
    answer = client.post(
        str(form["action"]),
        data=sent,
        headers={"HX-Request": "true", "HX-Current-URL": f"http://testserver{page}"},
    )
    return answer.status_code, answer.text, dict(answer.headers)


def annotated_through_the_page(
    client: TestClient, words: str, *, tags: str = "", comment: str = ""
) -> str:
    dialog = located(client, PAPER_PAGE, words)
    form = dialog.select_one("form.annotate")
    assert form is not None, dialog.get_text()
    status, text, _ = submitted(client, form, PAPER_PAGE, tags=tags, comment=comment)
    assert status == 200, text
    return text


def git_subject(root: Path) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Annotating a selection


def test_a_selection_is_annotated_with_its_tags_and_comment(corpus: Path) -> None:
    annotated_through_the_page(
        opened(), "gains were solved for", tags="Calibration", comment="Check per scan"
    )

    (annotation,) = read_annotations(corpus / ANNOTATIONS).annotations
    assert annotation.document == PAPER_ID
    assert annotation.tags == ("calibration",)
    assert annotation.comment == "Check per scan"
    assert annotation.selector is not None
    assert annotation.selector.exact == "gains were solved for"
    assert git_subject(corpus).startswith("tag(corpus)")


def test_a_comment_alone_is_kept(corpus: Path) -> None:
    annotated_through_the_page(opened(), "gains were solved for", comment="why?")

    (annotation,) = read_annotations(corpus / ANNOTATIONS).annotations
    assert (annotation.tags, annotation.comment) == ((), "why?")


def test_an_annotation_of_nothing_is_refused_in_the_dialog(corpus: Path) -> None:
    client = opened()
    form = located(client, PAPER_PAGE, "gains were solved for").select_one(
        "form.annotate"
    )
    assert form is not None

    status, text, headers = submitted(client, form, PAPER_PAGE)

    assert status == 200
    assert headers.get("x-kennis-refused") == "true"
    assert "needs a tag or a comment" in text
    assert not (corpus / ANNOTATIONS).exists()


def test_the_dialog_quotes_what_was_found(corpus: Path) -> None:
    dialog = located(opened(), PAPER_PAGE, "gains were solved for")

    quote = dialog.select_one("blockquote")
    assert quote is not None
    assert "gains were solved for" in quote.get_text()


def test_words_the_document_does_not_hold_are_not_offered(corpus: Path) -> None:
    dialog = located(opened(), PAPER_PAGE, SOLVING.split()[0])
    form = dialog.select_one("form.annotate")
    assert form is not None  # the fixture's own words are found

    client = opened()
    page = page_of(client, PAPER_PAGE)
    block = page.select_one("article [data-source]")
    assert block is not None
    answer = client.post(
        "/annotate/located",
        data={
            "document": PAPER_ID,
            "collection": "literature",
            "first": str(block["data-source"]),
            "last": str(block["data-source"]),
            "text": "words nowhere in the paper",
        },
        headers={"HX-Request": "true"},
    )

    missing = BeautifulSoup(answer.text, "html.parser")
    assert missing.select_one("form.annotate") is None
    assert "could not be matched" in missing.get_text()


def test_a_document_changed_since_the_selection_is_not_written(corpus: Path) -> None:
    client = opened()
    form = located(client, PAPER_PAGE, "gains were solved for").select_one(
        "form.annotate"
    )
    assert form is not None
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace("gains were solved", "gains came"),
        encoding="utf-8",
    )

    _, text, headers = submitted(client, form, PAPER_PAGE, tags="calibration")

    assert headers.get("x-kennis-refused") == "true"
    assert "changed since the text was selected" in text
    assert not (corpus / ANNOTATIONS).exists()


def test_the_answer_redraws_the_text_and_the_inspector(corpus: Path) -> None:
    answer = annotated_through_the_page(
        opened(), "gains were solved for", tags="calibration"
    )

    hooks = BeautifulSoup(answer, "html.parser").select("[data-redraw-id]")
    assert {str(hook["data-redraw-id"]) for hook in hooks} >= {
        "document-text",
        "document-annotations",
        "document-tags",
    }
    assert {str(hook["data-redraw-route"]) for hook in hooks} == {PAPER_PAGE}


# ---------------------------------------------------------------------------
# What the page draws of its annotations


def test_the_page_carries_where_each_annotation_is_and_its_words(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="calibration")

    page = page_of(client, PAPER_PAGE)
    data = page.select_one("article script[data-annotations]")
    assert data is not None
    (highlight,) = json.loads(data.get_text())
    body = (corpus / "literature" / "smirnov.md").read_text(encoding="utf-8")
    (annotation,) = read_annotations(corpus / ANNOTATIONS).annotations
    assert highlight["id"] == annotation.id
    assert highlight["words"] == ["gains", "were", "solved", "for"]
    assert highlight["href"] == f"/annotations/{annotation.id}"
    assert highlight["end"] - highlight["start"] == len("gains were solved for")
    assert "gains were solved for" in body


def test_the_inspector_lists_the_annotation_with_its_comment(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", comment="Per scan?")

    rows = page_of(client, PAPER_PAGE).select("#document-annotations li.annotation-row")

    (row,) = rows
    assert "gains were solved for" in row.get_text()
    assert "Per scan?" in row.get_text()
    assert row.select_one("a[href^='/annotations/']") is not None


def test_a_selection_whose_words_are_gone_is_listed_detached(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="calibration")
    paper = corpus / "literature" / "smirnov.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace("gains were solved", "gains came"),
        encoding="utf-8",
    )

    page = page_of(client, PAPER_PAGE)

    (row,) = page.select("#document-annotations li.annotation-row")
    assert row.has_attr("data-detached")
    data = page.select_one("article script[data-annotations]")
    assert data is not None and json.loads(data.get_text()) == []


# ---------------------------------------------------------------------------
# Changing and deleting


def edit_dialog(client: TestClient) -> BeautifulSoup:
    page = page_of(client, PAPER_PAGE)
    link = page.select_one("#document-annotations a[href^='/annotations/']")
    assert link is not None
    return page_of(client, str(link["href"]))


def test_the_annotation_s_dialog_saves_its_tags_and_comment(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="a", comment="x")
    form = edit_dialog(client).select_one("form.annotation")
    assert form is not None
    tags = form.select_one("input[name=tags]")
    comment = form.select_one("textarea[name=comment]")
    assert tags is not None and comment is not None
    assert (tags["value"], comment.get_text()) == ("a", "x")

    status, text, _ = submitted(client, form, PAPER_PAGE, tags="b, c", comment="y")

    assert status == 200, text
    (annotation,) = read_annotations(corpus / ANNOTATIONS).annotations
    assert (annotation.tags, annotation.comment) == (("b", "c"), "y")


def test_emptying_an_annotation_removes_it(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="a")
    form = edit_dialog(client).select_one("form.annotation")
    assert form is not None

    submitted(client, form, PAPER_PAGE, tags="", comment="")

    assert read_annotations(corpus / ANNOTATIONS).annotations == ()


def test_the_annotation_s_dialog_deletes_it(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="a")
    form = edit_dialog(client).select_one("form.annotation-delete")
    assert form is not None

    status, text, _ = submitted(client, form, PAPER_PAGE)

    assert status == 200, text
    assert read_annotations(corpus / ANNOTATIONS).annotations == ()


def test_an_unknown_annotation_is_a_problem_page(corpus: Path) -> None:
    answer = opened().get("/annotations/ffffffff")

    problem = BeautifulSoup(answer.text, "html.parser").get_text()
    assert "no annotation has the id 'ffffffff'" in problem


def test_a_plain_form_returns_to_the_page_it_came_from(corpus: Path) -> None:
    client = opened()
    annotated_through_the_page(client, "gains were solved for", tags="a")
    page = page_of(client, PAPER_PAGE)
    link = page.select_one("#document-annotations a[href^='/annotations/']")
    assert link is not None
    dialog = BeautifulSoup(
        client.get(
            str(link["href"]), headers={"referer": f"http://testserver{PAPER_PAGE}"}
        ).text,
        "html.parser",
    )
    form = dialog.select_one("form.annotation-delete")
    assert form is not None

    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    assert answer.headers["location"] == PAPER_PAGE


# ---------------------------------------------------------------------------
# A project's file


@pytest.fixture
def project(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    (root / ".context" / "ours.md").write_text(
        "---\ntitle: Ours\n---\nWe solve the gains per scan here.\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    run("context", "index")
    return root / ".context"


def test_a_project_s_file_is_annotated_in_its_own_store(
    corpus: Path, project: Path
) -> None:
    client = opened()
    address = "/bundle/ours.md?project=pipelines"
    form = located(client, address, "gains per scan").select_one("form.annotate")
    assert form is not None

    submitted(client, form, address, comment="ours")
    (annotation,) = read_annotations(project / ANNOTATIONS).annotations
    assert (annotation.document, annotation.comment) == ("ours.md", "ours")
    assert not (corpus / ANNOTATIONS).exists()

    link = page_of(client, address).select_one(
        "#document-annotations a[href^='/annotations/']"
    )
    assert link is not None
    assert str(link["href"]) == f"/annotations/{annotation.id}?project=pipelines"
    delete = page_of(client, str(link["href"])).select_one("form.annotation-delete")
    assert delete is not None
    submitted(client, delete, address)
    assert read_annotations(project / ANNOTATIONS).annotations == ()
