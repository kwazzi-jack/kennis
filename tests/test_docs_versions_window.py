"""The window chooses docs versions and shows them (#489, unit V3).

Each docs result names its version; a choice of versions beside the search
box travels in the address and is drawn from it; a document page links to
the same page in the other versions held; and the tree marks each
project's current version and can make another current.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.corpus.ids import derive_id, natural_key_for_docs
from kennis.engine.docs.versions import project_versions
from kennis.gui import history
from kennis.gui.app import build_app

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}

SAME = "Validators run after parsing and may raise a ValueError."


def models_page(changed: str) -> str:
    return (
        "# Models\n\n"
        "## Validation\n\n"
        f"{SAME}\n\n"
        "## Configuration\n\n"
        f"Configuration lives in {changed}, which sets validators too.\n"
    )


def a_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, versions: tuple[str, ...]
) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for version in versions:
        source = tmp_path / version / "models.md"
        source.parent.mkdir()
        source.write_text(models_page(f"setting {version}"), encoding="utf-8")
        adding = ["corpus", "add", "-d", "--project", "pydantic", "--version"]
        result = run.invoke(main, [*adding, version, str(source)])
        assert result.exit_code == 0, result.output
    assert run.invoke(main, ["corpus", "index", "--collection", "docs"]).exit_code == 0
    return tmp_path / "corpus"


def a_client() -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return a_corpus(tmp_path, monkeypatch, ("2.12", "2.14"))


@pytest.fixture
def client(corpus: Path) -> TestClient:
    return a_client()


def page(client: TestClient, address: str) -> BeautifulSoup:
    answer = client.get(address)
    assert answer.status_code == 200, answer.text[:300]
    return BeautifulSoup(answer.text, "html.parser")


def version_boxes(soup: BeautifulSoup) -> dict[str, bool]:
    """Each version checkbox of the search form, and whether it is ticked."""
    form = soup.select_one("form.searchbox")
    assert isinstance(form, Tag)
    return {
        str(box["value"]): box.has_attr("checked")
        for box in form.select('.versions input[type="checkbox"][name="version"]')
    }


def labels_of(soup: BeautifulSoup) -> list[str]:
    return [label.get_text(strip=True) for label in soup.select(".hit .hit-version")]


SEARCH = "/?q=validators&scope=docs&k=10"


# ---------------------------------------------------------------------------
# A result says its version
# ---------------------------------------------------------------------------


def test_a_docs_result_names_its_version(client: TestClient):
    labels = labels_of(page(client, SEARCH))

    assert labels and set(labels) == {"pydantic 2.14"}


# ---------------------------------------------------------------------------
# The choice beside the box
# ---------------------------------------------------------------------------


def test_the_box_offers_each_version_with_the_current_one_ticked(client: TestClient):
    assert version_boxes(page(client, "/")) == {
        "pydantic=2.12": False,
        "pydantic=2.14": True,
    }


def test_the_current_version_is_marked_as_such(client: TestClient):
    current = page(client, "/").select_one('.versions [data-current="true"]')

    assert isinstance(current, Tag)
    assert "2.14" in current.get_text()


def test_with_one_version_there_is_nothing_to_choose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    a_corpus(tmp_path, monkeypatch, ("2.14",))

    assert version_boxes(page(a_client(), "/")) == {}


def test_the_ticked_versions_come_from_the_address(client: TestClient):
    chosen = "&version=pydantic%3D2.12&version=pydantic%3D2.14"
    soup = page(client, SEARCH + chosen)

    assert version_boxes(soup) == {"pydantic=2.12": True, "pydantic=2.14": True}
    assert "pydantic 2.12, 2.14" in labels_of(soup)


def test_the_drawn_choice_submitted_searches_what_it_says(client: TestClient):
    """The form the page drew, ticked by a reader and sent as it stands."""
    soup = page(client, SEARCH)
    form = soup.select_one("form.searchbox")
    assert isinstance(form, Tag)
    sent: list[tuple[str, str]] = [("q", "validators"), ("scope", "docs")]
    for box in form.select('.versions input[name="version"]'):
        # The reader ticks 2.12 beside the current one.
        sent.append(("version", str(box["value"])))

    answer = client.get("/hits", params=sent, headers=HTMX)

    assert "pydantic 2.12, 2.14" in answer.text


def test_the_default_choice_leaves_the_address_as_it_was(client: TestClient):
    answer = client.get(
        "/hits",
        params={"q": "validators", "scope": "docs", "version": "pydantic=2.14"},
        headers=HTMX,
    )

    assert "version" not in answer.headers["HX-Push-Url"]


def test_another_choice_is_pushed_into_the_address(client: TestClient):
    answer = client.get(
        "/hits",
        params={"q": "validators", "scope": "docs", "version": "pydantic=2.12"},
        headers=HTMX,
    )

    pushed = parse_qs(urlsplit(answer.headers["HX-Push-Url"]).query)
    assert pushed["version"] == ["pydantic=2.12"]


def test_more_and_the_orders_carry_the_choice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_RETRIEVAL_DEFAULT_TOP_K", "1")
    soup = page(client, "/?q=validators&scope=docs&version=all")

    rerunning = [
        str(link["href"])
        for link in soup.select(".more a, .order a")
        if "q=" in str(link["href"])
    ]
    assert rerunning
    assert all("version=all" in href for href in rerunning)


def test_a_recent_search_remembers_its_versions(client: TestClient):
    page(client, "/?q=validators&scope=docs&version=all")

    assert history.recent()[0].versions == ("all",)
    link = page(client, "/").select_one(".recents a")
    assert isinstance(link, Tag)
    assert "version=all" in str(link["href"])


def test_an_unknown_version_is_said_rather_than_failing(client: TestClient):
    soup = page(client, SEARCH + "&version=9.9")

    assert "9.9" in soup.get_text()
    assert labels_of(soup) == []


# ---------------------------------------------------------------------------
# A document's other versions
# ---------------------------------------------------------------------------


def document_id(version: str) -> str:
    return derive_id(
        natural_key_for_docs(project="pydantic", version=version, page="models")
    )


def test_a_document_links_to_the_same_page_in_the_other_versions(client: TestClient):
    soup = page(client, f"/document/docs/{document_id('2.14')}")

    others = soup.select(".other-versions a")
    assert [link.get_text(strip=True) for link in others] == ["2.12"]
    assert others[0]["href"] == f"/document/docs/{document_id('2.12')}"


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def version_row(soup: BeautifulSoup, version: str) -> Tag:
    row = soup.select_one(f'li.group[data-group="pydantic/{version}"]')
    assert isinstance(row, Tag), version
    return row


def test_the_tree_marks_the_current_version(client: TestClient):
    soup = page(client, "/tree/docs")

    assert version_row(soup, "2.14").select_one(".current-version") is not None
    assert version_row(soup, "2.12").select_one(".current-version") is None


def test_another_version_can_be_made_current_from_its_menu(
    client: TestClient, corpus: Path
):
    form = version_row(page(client, "/tree/docs"), "2.12").select_one(
        "form.make-current"
    )
    assert isinstance(form, Tag)
    fields = {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
    }

    answer = client.post(str(form["action"]), data=fields, headers=HTMX)

    assert answer.status_code == 200
    assert project_versions(corpus / "docs")["pydantic"].current == "2.12"
    assert set(labels_of(page(client, SEARCH))) == {"pydantic 2.12"}


def test_the_current_version_offers_no_menu_entry_to_become_current(
    client: TestClient,
):
    row = version_row(page(client, "/tree/docs"), "2.14")

    assert row.select_one("form.make-current") is None


# ---------------------------------------------------------------------------
# Removing a version from the tree (V4)
# ---------------------------------------------------------------------------


def removal_link(client: TestClient, version: str) -> str:
    link = version_row(page(client, "/tree/docs"), version).select_one(
        "a.remove-version"
    )
    assert isinstance(link, Tag), version
    return str(link["href"])


def removal_dialog(client: TestClient, version: str) -> BeautifulSoup:
    answer = client.get(removal_link(client, version), headers=HTMX)
    assert answer.status_code == 200, answer.text[:300]
    return BeautifulSoup(answer.text, "html.parser")


def test_every_version_offers_to_remove_it(client: TestClient):
    for version in ("2.12", "2.14"):
        assert "version=" + version in removal_link(client, version)


def test_the_removal_dialog_says_what_goes_before_anything_does(
    client: TestClient, corpus: Path
):
    dialog = removal_dialog(client, "2.12")

    assert dialog.select_one("dialog") is not None
    assert "pydantic 2.12" in dialog.get_text()
    assert "1 document" in dialog.get_text()
    assert project_versions(corpus / "docs")["pydantic"].held == ("2.12", "2.14")


def test_the_drawn_removal_form_removes_the_version(client: TestClient, corpus: Path):
    form = removal_dialog(client, "2.12").select_one("form.remove-version")
    assert isinstance(form, Tag)
    assert form.has_attr("data-closes-dialog")
    fields = {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
    }

    answer = client.post(str(form["action"]), data=fields, headers=HTMX)

    assert answer.status_code == 200
    assert project_versions(corpus / "docs")["pydantic"].held == ("2.14",)
    redrawn = BeautifulSoup(answer.text, "html.parser")
    assert redrawn.select_one('li.group[data-group="pydantic/2.12"]') is None
    assert redrawn.select_one('li.group[data-group="pydantic/2.14"]') is not None


def test_removing_a_version_without_a_script_returns_to_the_collection(
    client: TestClient,
):
    answer = client.post(
        "/docs/remove-version", data={"project": "pydantic", "version": "2.12"}
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == "/collection/docs"


def test_a_removal_of_a_version_not_held_names_the_ones_that_are(
    client: TestClient,
):
    answer = client.get(
        "/docs/remove-version", params={"project": "pydantic", "version": "9.9"}
    )

    assert "9.9" in answer.text
    assert "2.12" in answer.text and "2.14" in answer.text
