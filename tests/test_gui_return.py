"""The window removes a document, puts one back, and returns the corpus to a
point - by the operations the command line runs (Brian, 2026-10-18).

The tree's document menu offers Remove; the Activity page's corpus history
offers each earlier point to return to, and each document a removal took to
put back. Every one is a page and a form, asked before anything changes,
and each test submits the form the page drew.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.history.history import read_history
from kennis.engine.history.repository import Repository
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for name in ("kept", "later"):
        source = tmp_path / "sources" / f"{name}.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# {name}\n\nThe {name} note.\n", encoding="utf-8")
        result = run.invoke(main, ["corpus", "add", "-n", str(source)])
        assert result.exit_code == 0, result.output
    return tmp_path / "corpus"


@pytest.fixture
def client(corpus: Path) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def soup_of(text: str) -> BeautifulSoup:
    return BeautifulSoup(text, "html.parser")


def titles(corpus: Path) -> list[str]:
    held = Collection(root=corpus, name="notes").contents().documents
    return sorted(document.frontmatter.title for document in held)


def latest(corpus: Path) -> str | None:
    return read_history(Repository(corpus), limit=1)[0].operation


def submitted(
    client: TestClient, form: Tag, *, htmx: bool = False
) -> tuple[int, str, str]:
    """Post the drawn form to the route it names, with exactly its fields."""
    action = str(form.get("hx-post") or form.get("action"))
    fields = {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
    }
    answer = client.post(action, data=fields, headers=HTMX if htmx else {})
    return answer.status_code, answer.headers.get("location", ""), answer.text


def name_of(row: Tag) -> str:
    found = row.select_one(".name")
    return found.get_text() if isinstance(found, Tag) else ""


def removal_form(client: TestClient, title: str, *, htmx: bool = False) -> Tag:
    tree = soup_of(client.get("/tree/notes", headers=HTMX).text)
    row = next(one for one in tree.select("li.row") if name_of(one) == title)
    link = row.select_one("a.item.remove-document")
    assert isinstance(link, Tag), "the document's menu offers no Remove"
    dialog = soup_of(client.get(str(link["href"]), headers=HTMX if htmx else {}).text)
    assert title in dialog.get_text()
    form = dialog.select_one("form.remove-document")
    assert isinstance(form, Tag)
    return form


# ---------------------------------------------------------------------------
# Removing from the tree
# ---------------------------------------------------------------------------


def test_the_tree_removes_a_document_after_asking(corpus: Path, client: TestClient):
    status, _, answer = submitted(
        client, removal_form(client, "kept", htmx=True), htmx=True
    )

    assert status == 200
    assert titles(corpus) == ["later"]
    assert latest(corpus) == "remove"
    assert 'id="pane-branch-notes"' in answer
    assert "kept" not in soup_of(answer).select_one("#pane-branch-notes").get_text()


def test_without_a_script_a_removal_returns_to_the_collection(
    corpus: Path, client: TestClient
):
    status, location, _ = submitted(client, removal_form(client, "kept"))

    assert (status, location) == (303, "/collection/notes")
    assert titles(corpus) == ["later"]


def test_asking_to_remove_changes_nothing(corpus: Path, client: TestClient):
    removal_form(client, "kept")

    assert titles(corpus) == ["kept", "later"]


# ---------------------------------------------------------------------------
# Returning from the Activity page
# ---------------------------------------------------------------------------


def changes_rows(client: TestClient) -> list[Tag]:
    activity = soup_of(client.get("/activity").text)
    return activity.select("table.changes tr")


def return_link(row: Tag) -> Tag | None:
    found = row.select_one("a.return-here")
    return found if isinstance(found, Tag) else None


def test_every_point_but_the_newest_can_be_returned_to(client: TestClient):
    rows = changes_rows(client)

    assert return_link(rows[0]) is None
    assert all(return_link(row) is not None for row in rows[1:])


def test_a_return_is_asked_with_what_it_would_change_and_then_done(
    corpus: Path, client: TestClient
):
    # The second row is the point where only `kept` was held.
    link = return_link(changes_rows(client)[1])
    assert link is not None
    asked = soup_of(client.get(str(link["href"])).text)
    assert "later" in asked.get_text()
    assert titles(corpus) == ["kept", "later"]
    form = asked.select_one("form.return-corpus")
    assert isinstance(form, Tag)

    status, _, answer = submitted(client, form)

    assert status == 200
    assert titles(corpus) == ["kept"]
    assert latest(corpus) == "return"
    # The result's own section: the bar on every page links to /index too.
    result = soup_of(answer).select_one("main .action-page")
    assert isinstance(result, Tag)
    assert result.select_one('a[href="/index"]') is not None, (
        "no way to rebuild the index"
    )


def test_returning_to_where_the_corpus_is_offers_no_form(client: TestClient):
    head = read_history(Repository(existing_corpus().corpus_root), limit=1)[0].commit

    asked = soup_of(client.get(f"/corpus/return?commit={head}").text)

    assert asked.select_one("form.return-corpus") is None


def test_a_point_that_is_not_there_is_refused_by_name(client: TestClient):
    answer = client.get("/corpus/return?commit=0123456789abcdef")

    assert "0123456789abcdef" in answer.text
    assert "form" not in answer.text or "return-corpus" not in answer.text


def test_a_removal_on_the_activity_page_offers_to_put_back_what_it_took(
    corpus: Path, client: TestClient
):
    submitted(client, removal_form(client, "kept"))
    rows = changes_rows(client)
    put_back = rows[0].select_one("form.put-back")
    assert isinstance(put_back, Tag)
    assert "kept" in rows[0].get_text()

    status, _, _ = submitted(client, put_back)

    assert status in (200, 303)
    assert titles(corpus) == ["kept", "later"]
    assert latest(corpus) == "restore"
