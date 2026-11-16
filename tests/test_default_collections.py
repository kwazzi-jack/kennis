"""Which collections a default search covers, and in what order (#669).

`retrieval.default_collections` is the reader's: a default search covers
the scopes it lists and no others, every search shows its groups in that
order, and a scope left out is still searched when it is named. What this
file holds is that the three front ends follow the one setting and that
each says what it left out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kennis.cli.__main__ import main
from kennis.engine.settings import RetrievalSettings, default_scopes
from kennis.engine.setup import apply_answers
from kennis.gui.app import build_app
from kennis.mcp.tools.search import search
from kennis.retrieval import sweep

TOKEN = "a-test-token"
KEY = "retrieval.default_collections"


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A note and a docs page that both match "gains", both indexed."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "note.md").write_text(
        "# Drift\n\nAntenna gains drift on long tracks.\n", encoding="utf-8"
    )
    (sources / "page.md").write_text(
        "# Solver\n\nThe solver applies antenna gains per interval.\n",
        encoding="utf-8",
    )
    assert (
        run.invoke(main, ["corpus", "add", "-n", str(sources / "note.md")]).exit_code
        == 0
    )
    added = run.invoke(
        main,
        [
            "corpus",
            "add",
            "-d",
            str(sources / "page.md"),
            "--project",
            "stimela",
            "--version",
            "latest",
        ],
    )
    assert added.exit_code == 0, added.output
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    return tmp_path


def swept(scopes: tuple[str, ...] | None = None, *, named: bool = False) -> list[str]:
    return list(sweep("gains", scopes=scopes, named=named, bundle=None).groups)


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_the_default_is_every_scope_in_the_order_kennis_always_had():
    """Written by hand: compared with `SCOPE_NAMES` it would follow a
    change to that tuple and say nothing (#373)."""
    assert default_scopes(RetrievalSettings().default_collections) == (
        "context",
        "literature",
        "docs",
        "notes",
    )


@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("notes docs", ("notes", "docs")),
        ("notes, docs", ("notes", "docs")),
        ("  Literature  ", ("literature",)),
        ("notes,context,docs,literature", ("notes", "context", "docs", "literature")),
    ],
)
def test_the_list_is_read_in_the_order_written(written: str, read: tuple[str, ...]):
    settings = RetrievalSettings(default_collections=written)

    assert default_scopes(settings.default_collections) == read


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("notes papers", "papers"),
        ("notes notes", "twice"),
        ("notes Notes", "twice"),
        ("", "at least one"),
        (" , ", "at least one"),
    ],
)
def test_a_list_that_cannot_be_a_default_is_refused(written: str, said: str):
    with pytest.raises(ValidationError) as refused:
        RetrievalSettings(default_collections=written)

    assert said in str(refused.value)


def test_an_unknown_name_is_told_the_names_there_are():
    with pytest.raises(ValidationError) as refused:
        RetrievalSettings(default_collections="papers")

    for name in ("context", "literature", "docs", "notes"):
        assert name in str(refused.value)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_a_default_search_shows_its_groups_in_the_order_set(corpus: Path):
    assert swept() == ["docs", "notes"]

    apply_answers({KEY: "notes docs"})

    assert swept() == ["notes", "docs"]


def test_a_default_search_does_not_search_a_collection_left_out(corpus: Path):
    apply_answers({KEY: "notes"})

    found = sweep("gains", scopes=None, named=False, bundle=None)

    assert list(found.groups) == ["notes"]
    assert found.searched == ("notes",)
    assert found.left_out == ("context", "literature", "docs")


def test_nothing_is_left_out_until_the_reader_leaves_something_out(corpus: Path):
    assert sweep("gains", scopes=None, named=False, bundle=None).left_out == ()


def test_a_collection_left_out_is_still_searched_when_named(corpus: Path):
    apply_answers({KEY: "notes"})

    found = sweep("gains", scopes=("docs",), named=True, bundle=None)

    assert list(found.groups) == ["docs"]
    assert found.left_out == ()


def test_scopes_given_are_searched_as_given_whatever_the_default(corpus: Path):
    """Every scope by name is how to search everything once, with the
    default narrowed."""
    apply_answers({KEY: "notes"})

    found = sweep(
        "gains",
        scopes=("context", "literature", "docs", "notes"),
        named=False,
        bundle=None,
    )

    assert set(found.groups) == {"notes", "docs"}
    assert found.left_out == ()


@pytest.mark.parametrize(
    ("setting", "shown"),
    [
        ("notes docs", ["notes", "docs"]),
        ("docs notes", ["docs", "notes"]),
        # Listed first, then the others in the order kennis always had.
        ("notes", ["notes", "docs"]),
        ("literature", ["docs", "notes"]),
    ],
)
def test_named_scopes_are_shown_in_the_order_set_too(
    corpus: Path, setting: str, shown: list[str]
):
    apply_answers({KEY: setting})

    assert swept(("docs", "notes"), named=True) == shown
    assert swept(("notes", "docs"), named=True) == shown


def test_a_collection_left_out_and_not_indexed_is_not_called_skipped(
    corpus: Path, tmp_path: Path
):
    """It was not reached because the reader left it out, which is a
    different thing from having no index and has a different remedy."""
    paper = tmp_path / "sources" / "second.md"
    paper.write_text("# Second\n\nMore about gains.\n", encoding="utf-8")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "index", "--collection", "notes"]).exit_code == 0
    (tmp_path / "corpus" / "index" / "docs").rename(tmp_path / "docs-index-gone")
    assert "docs" in {
        entry.name
        for entry in sweep("gains", scopes=None, named=False, bundle=None).skipped
    }, "the fixture no longer leaves docs without an index"

    apply_answers({KEY: "notes"})
    found = sweep("gains", scopes=None, named=False, bundle=None)

    assert "docs" not in {entry.name for entry in found.skipped}
    assert "docs" in found.left_out


def test_no_scopes_and_a_promise_is_a_mistake_in_the_caller(corpus: Path):
    with pytest.raises(ValueError, match="named"):
        sweep("gains", scopes=None, named=True, bundle=None)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_kennis_search_follows_the_setting_and_says_what_it_left_out(corpus: Path):
    run = CliRunner()
    apply_answers({KEY: "notes"})

    result = run.invoke(main, ["search", "gains"])

    assert result.exit_code == 0, result.output
    assert "Drift" in result.output
    assert "Solver" not in result.output
    (said,) = [line for line in result.output.splitlines() if "left out" in line]
    assert "docs" in said and "notes" not in said


def test_kennis_search_says_nothing_of_it_when_nothing_is_left_out(corpus: Path):
    result = CliRunner().invoke(main, ["search", "gains"])

    assert result.exit_code == 0, result.output
    assert "Solver" in result.output and "Drift" in result.output
    assert "left out" not in result.output


def test_kennis_search_reaches_a_collection_left_out_by_its_name(corpus: Path):
    apply_answers({KEY: "notes"})

    result = CliRunner().invoke(main, ["search", "gains", "--collection", "docs"])

    assert result.exit_code == 0, result.output
    assert "Solver" in result.output
    assert "left out" not in result.output


def test_kennis_search_prints_its_groups_in_the_order_set(corpus: Path):
    apply_answers({KEY: "notes docs"})

    output = CliRunner().invoke(main, ["search", "gains"]).output

    assert output.index("Drift") < output.index("Solver")


# ---------------------------------------------------------------------------
# An agent
# ---------------------------------------------------------------------------


def test_an_agent_s_all_is_the_reader_s_default_and_says_what_it_left_out(
    corpus: Path,
):
    apply_answers({KEY: "notes"})

    answer = search("gains", ["all"])

    assert "Drift" in answer
    assert "Solver" not in answer
    (said,) = [line for line in answer.splitlines() if "left out" in line]
    assert "docs" in said
    # What an agent can do about it is an argument, not a command.
    assert "collections" in said


def test_an_agent_reaches_a_collection_left_out_by_naming_it(corpus: Path):
    apply_answers({KEY: "notes"})

    answer = search("gains", ["docs"])

    assert "Solver" in answer
    assert "left out" not in answer


def test_an_agent_s_groups_are_in_the_order_set(corpus: Path):
    apply_answers({KEY: "notes docs"})

    answer = search("gains", ["all"])

    assert answer.index("Drift") < answer.index("Solver")


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def page_of_hits(question: str = "gains", **query: str) -> BeautifulSoup:
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    client.get("/", params={"token": TOKEN})
    answered = client.get("/hits", params={"q": question, **query})
    assert answered.status_code == 200, answered.text
    return BeautifulSoup(answered.text, "html.parser")


def groups_drawn(page: BeautifulSoup) -> list[str]:
    return [str(head["data-collection"]) for head in page.select("h2.group-head")]


def test_the_window_draws_its_groups_in_the_order_set(corpus: Path):
    assert groups_drawn(page_of_hits()) == ["docs", "notes"]

    apply_answers({KEY: "notes docs"})

    assert groups_drawn(page_of_hits()) == ["notes", "docs"]


def test_the_window_says_what_was_left_out_with_a_way_to_search_it(corpus: Path):
    apply_answers({KEY: "notes"})

    page = page_of_hits()

    assert groups_drawn(page) == ["notes"]
    (said,) = page.select("p.left-out")
    offered = {
        link.get_text(strip=True): str(link["href"]) for link in said.select("a.button")
    }
    assert set(offered) == {"context", "literature", "docs"}
    assert "scope=docs" in offered["docs"]
    assert "q=gains" in offered["docs"]
    # The address it offers answers, with the collection that was left out.
    assert groups_drawn(page_of_hits(scope="docs")) == ["docs"]


def test_the_window_says_nothing_of_it_when_nothing_is_left_out(corpus: Path):
    assert page_of_hits().select("p.left-out") == []


def test_a_named_scope_in_the_window_says_nothing_is_left_out(corpus: Path):
    apply_answers({KEY: "notes"})

    assert page_of_hits(scope="notes").select("p.left-out") == []
