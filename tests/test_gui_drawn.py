"""What the browser still drew for itself, and the pages left plain.

Brian, 2026-10-16: the progress bar should "match the theme", the search
bar's dropdown "is unstyled", and "go through all components". Measured
by an audit of every control on every page and dialog in both themes
(`sketches/2026-10-16-what-the-browser-still-drew.md`).
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

TOKEN = "a-test-token"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    note = tmp_path / "rivers.md"
    note.write_text("# Rivers\n\nRivers carry sediment.\n", encoding="utf-8")
    adding = ["corpus", "add", "-n", "--group", "earth", str(note)]
    assert CliRunner().invoke(main, adding).exit_code == 0
    return tmp_path


@pytest.fixture
def client(corpus: Path) -> TestClient:
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def code() -> str:
    return re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)


def rule_for(css: str, selector: str) -> str:
    found = [
        body
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if head.strip() == selector
    ]
    assert len(found) == 1, (selector, len(found))
    return found[0]


# ---------------------------------------------------------------------------
# What the browser draws for itself follows the theme
# ---------------------------------------------------------------------------


def test_each_theme_tells_the_browser_its_scheme():
    """A select's list, a search field's cross and a number field's arrows
    were drawn light in the dark theme: no `color-scheme` was declared."""
    css = code()
    light = re.search(r"^:root \{([^}]*)\}", css, re.M)
    dark_blocks = re.findall(
        r':root(?::not\(\[data-theme="light"\]\)|\[data-theme="dark"\]) \{([^}]*)\}',
        css,
    )

    assert light and "color-scheme: light;" in light.group(1)
    assert len(dark_blocks) == 2
    assert all("color-scheme: dark;" in block for block in dark_blocks)


def test_a_progress_bar_is_the_theme_s():
    css = code()

    assert "appearance: none" in rule_for(css, "progress")
    assert "var(--role-command)" in rule_for(css, "progress::-webkit-progress-value")
    assert "var(--role-command)" in rule_for(css, "progress::-moz-progress-bar")
    assert "var(--rule)" in rule_for(css, "progress::-webkit-progress-bar")


def test_a_select_s_open_list_is_drawn_by_the_page_where_it_can_be():
    css = stylesheet()
    supported = re.search(
        r"@supports \(appearance: base-select\) \{(.*?)\n\}\n", css, re.S
    )

    assert supported
    block = supported.group(1)
    assert re.search(
        r"select, ::picker\(select\) \{ appearance: base-select; \}", block
    )
    assert re.search(r"::picker\(select\) \{[^}]*background: var\(--ground\)", block)
    assert re.search(r"option:checked \{[^}]*var\(--brand-wash\)", block)


def test_the_search_field_s_cross_is_cut_from_the_vendored_icon():
    css = code()
    cross = rule_for(css, 'input[type="search"]::-webkit-search-cancel-button')

    assert "appearance: none" in cross
    assert "var(--cross)" in cross
    assert 'url("/static/vendor/icons/x.svg")' in css


def test_a_segmented_control_is_as_wide_as_its_buttons():
    """In a column it stretched to the dialog's width, an empty box after
    its last button."""
    segmented = rule_for(code(), ".segmented")

    assert "align-self: flex-start" in segmented
    assert "width: fit-content" in segmented


# ---------------------------------------------------------------------------
# The pages left plain
# ---------------------------------------------------------------------------


def test_a_collection_lists_each_document_as_a_row(client: TestClient):
    page = BeautifulSoup(client.get("/collection/notes").text, "html.parser")
    row = page.select_one("ul.documents li a")

    assert isinstance(row, Tag)
    assert row.find("svg") is not None
    assert row.get_text(strip=True) == "rivers"
    # The id is a handle for a program, not a word for a reader.
    document_id = str(row["href"]).rsplit("/", 1)[1]
    assert document_id not in page.select_one("ul.documents").get_text()
    assert row["title"] == document_id


def test_a_document_row_is_not_underlined():
    rows = rule_for(code(), ".documents a")

    assert "text-decoration: none" in rows
    assert "display: flex" in rows


def test_the_corpus_page_draws_each_collection_with_its_icon_and_colour(
    client: TestClient,
):
    page = BeautifulSoup(client.get("/corpus").text, "html.parser")

    for name in ("literature", "docs", "notes"):
        link = page.select_one(f'.holdings a[href="/collection/{name}"]')
        assert isinstance(link, Tag), name
        assert link.find("svg") is not None, name
        assert link.find_parent(attrs={"data-collection": name}) is not None, name


# ---------------------------------------------------------------------------
# Words the audit found
# ---------------------------------------------------------------------------


def test_a_history_line_shows_a_summary_only_when_it_counts_something():
    assert words.change_line("init", "corpus", "create the corpus") == (
        "created corpus"
    )
    assert words.change_line("index", "corpus", "2 documents, 2 chunks") == (
        "indexed corpus (2 documents, 2 chunks)"
    )


def test_a_sync_s_headline_begins_with_a_capital():
    from kennis.engine.corpus.sync import CorpusSync
    from kennis.gui.pages import shown_corpus_sync

    shown = shown_corpus_sync(CorpusSync(actions=(), counts={}, deferred=(), edited=()))

    assert shown.headline[:1].isupper(), shown.headline
