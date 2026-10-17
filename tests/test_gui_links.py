"""What a link looks like, by what it does (Brian, 2026-10-17).

"Could we make that look a little more clean than just a hyperlink? ...
scrutinise [our] hyperlinks in the gui." An inventory of every visible link
found five kinds still drawn as underlined text
(`sketches/2026-10-17-what-a-link-looks-like.md`). The rules:

- a link that continues a list is a control;
- a way out of a problem is a button (#475);
- a link that leaves kennis opens a new tab, tells it nothing, and says
  that it leaves;
- a list of places is rows.

Links in a document's own text stay underlined: they are the author's.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.theme import stylesheet
from kennis.render.html import to_html

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for number in range(5):
        source = tmp_path / "sources" / f"river-{number}.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            f"# River {number}\n\nRiver {number} carries sediment. "
            "See [the survey](https://example.org/survey) and [below](#below).\n",
            encoding="utf-8",
        )
        assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


@pytest.fixture
def client(corpus: Path) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def soup_of(client: TestClient, address: str, **params: str) -> BeautifulSoup:
    answer = client.get(address, params=params)
    assert answer.status_code == 200, answer.text[:300]
    return BeautifulSoup(answer.text, "html.parser")


def code() -> str:
    return re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)


def rule_for(selector: str) -> str:
    found = [
        body
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", code())
        if head.strip() == selector
    ]
    assert len(found) == 1, (selector, len(found))
    return found[0]


# ---------------------------------------------------------------------------
# A link that continues a list is a control
# ---------------------------------------------------------------------------


def test_more_from_a_collection_is_a_button_with_its_icon(client: TestClient):
    page = soup_of(client, "/", q="sediment", scope="notes")
    more = page.select_one(".more a")

    assert isinstance(more, Tag)
    assert "button" in (more.get("class") or [])
    assert more.find("svg") is not None
    assert more.get_text(strip=True) == words.more_from("notes")


def test_the_more_button_spans_the_results_column():
    rule = rule_for(".more .button")

    assert "width: 100%" in rule
    assert "justify-content: center" in rule


# ---------------------------------------------------------------------------
# A way out of a problem is a button
# ---------------------------------------------------------------------------


def test_the_keywords_only_notices_way_forward_is_a_button(client: TestClient):
    page = soup_of(client, "/", q="sediment", mode="dense")
    way = page.select_one(".notice.quiet a")

    assert isinstance(way, Tag)
    assert "button" in (way.get("class") or [])
    assert way["href"] == "/settings#setting-embedding.backend"


def test_with_a_model_the_way_forward_opens_the_index_dialog(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The index has no vectors and a model is configured, so building
    again is the step - in the dialog, as the bar's Index opens it."""
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "fastembed")
    page = soup_of(client, "/", q="sediment", mode="dense")
    way = page.select_one(".notice.quiet a")

    assert isinstance(way, Tag)
    assert way.get_text(strip=True) == words.KEYWORDS_ONLY_INDEX
    assert "button" in (way.get("class") or [])
    assert way["href"] == way["hx-get"] == "/index"
    assert way["hx-target"] == "#dialog"


# ---------------------------------------------------------------------------
# A link that leaves kennis
# ---------------------------------------------------------------------------


def test_a_documents_outside_link_opens_a_new_tab_that_learns_nothing():
    html = to_html("See [the survey](https://example.org/survey).")
    link = BeautifulSoup(html, "html.parser").find("a")

    assert isinstance(link, Tag)
    assert link["target"] == "_blank"
    assert set(link["rel"]) >= {"noopener", "noreferrer"}


def test_a_link_within_the_document_stays_in_the_tab():
    html = to_html("See [below](#below) and [the file](notes.md).")
    links = BeautifulSoup(html, "html.parser").find_all("a")

    assert len(links) == 2
    assert all(not link.has_attr("target") for link in links)


def test_every_outside_link_on_the_window_opens_a_new_tab(client: TestClient):
    """Read from drawn pages rather than templates, because a document's
    links come from its markdown."""
    hit = soup_of(client, "/", q="sediment", scope="notes").select_one("#hits a.title")
    assert isinstance(hit, Tag)
    pages = [
        soup_of(client, str(hit["href"]).split("?")[0]),
        soup_of(client, "/settings"),
    ]
    outside = [
        link
        for page in pages
        for link in page.find_all("a", href=re.compile(r"^https?://"))
    ]

    assert len(outside) >= 2
    for link in outside:
        assert link.get("target") == "_blank", link
        assert set(link.get("rel") or []) >= {"noopener", "noreferrer"}, link


def test_a_link_that_leaves_says_so():
    """One rule for every such link, so no template has to remember it; a
    button that leaves carries its own icon."""
    rule = rule_for('a[target="_blank"]:not(.button)::after')

    assert "var(--outward)" in rule
    assert 'url("/static/vendor/icons/arrow-up-right.svg")' in code()


# ---------------------------------------------------------------------------
# A list of places is rows
# ---------------------------------------------------------------------------


def test_a_documents_matches_are_rows():
    rule = rule_for(".matches a")

    assert "text-decoration: none" in rule
    assert "display: flex" in rule


def test_a_way_out_in_a_notice_sits_under_its_sentence():
    rule = rule_for(".notice .button")

    assert "display: flex" in rule
    assert "width: fit-content" in rule
