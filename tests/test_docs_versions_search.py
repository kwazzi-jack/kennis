"""A search uses each project's current version (#489, unit V2).

An ordinary search holds no duplicates across versions. The reader widens
it per search with `--version`, every docs hit names its version, and a
passage whose text is exactly equal in two versions of one page is shown
once, labelled with both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.docs.versions import ProjectVersions, excluded_versions
from kennis.engine.errors import InputError
from kennis.engine.rag.models import Chunk, Filter

HELD = {
    "pydantic": ProjectVersions(held=("2.12", "2.14"), current="2.14"),
    "stimela": ProjectVersions(held=("latest",), current="latest"),
}


# ---------------------------------------------------------------------------
# Which versions a search leaves out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chosen", "left_out"),
    [
        ((), ("pydantic/2.12",)),
        (("all",), ()),
        (("2.12",), ("pydantic/2.14",)),
        (("pydantic=2.12",), ("pydantic/2.14",)),
        (("pydantic=2.12", "pydantic=2.14"), ()),
        (("2.12", "2.14"), ()),
        # Naming stimela's leaves pydantic at its current.
        (("stimela=latest",), ("pydantic/2.12",)),
    ],
)
def test_the_versions_left_out(chosen: tuple[str, ...], left_out: tuple[str, ...]):
    assert excluded_versions(HELD, chosen) == left_out


@pytest.mark.parametrize("chosen", [("9.9",), ("pydantic=9.9",), ("numpy=1.0",)])
def test_a_version_nothing_holds_is_refused_with_what_is_held(
    chosen: tuple[str, ...],
):
    """A filter matching nothing would answer "no passages" to a typo."""
    with pytest.raises(InputError, match=r"2\.12"):
        excluded_versions(HELD, chosen)


def chunk_in(group: str | None) -> Chunk:
    metadata: dict[str, object] = {} if group is None else {"group": group}
    return Chunk(
        id="d::0",
        collection="docs",
        source_path="docs/x.md",
        document_id="d",
        chunk_index=0,
        text="t",
        char_start=0,
        char_end=1,
        metadata=metadata,
    )


def test_not_in_keeps_what_is_absent_from_the_list():
    keep = Filter(field="group", op="not_in", value=["pydantic/2.12"]).predicate()

    assert keep(chunk_in("pydantic/2.14"))
    assert not keep(chunk_in("pydantic/2.12"))
    # A chunk with no group is in no version, so nothing excludes it.
    assert keep(chunk_in(None))


# ---------------------------------------------------------------------------
# Through the command line
# ---------------------------------------------------------------------------

SAME = "Validators run after parsing and may raise a ValueError."


def models_page(changed: str) -> str:
    return (
        "# Models\n\n"
        "## Validation\n\n"
        f"{SAME}\n\n"
        "## Configuration\n\n"
        f"Configuration lives in {changed}, which sets validators too.\n"
    )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for version, changed in (("2.12", "the Config class"), ("2.14", "model_config")):
        source = tmp_path / version / "models.md"
        source.parent.mkdir()
        source.write_text(models_page(changed), encoding="utf-8")
        adding = ["corpus", "add", "-d", "--project", "pydantic", "--version"]
        result = run.invoke(main, [*adding, version, str(source)])
        assert result.exit_code == 0, result.output
    assert run.invoke(main, ["corpus", "index", "--collection", "docs"]).exit_code == 0
    return tmp_path / "corpus"


def searched(*extra: str) -> str:
    result = CliRunner().invoke(
        main,
        ["search", "validators", "--collection", "docs", "-k", "10", *extra],
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_a_search_uses_the_current_version_alone(corpus: Path):
    output = searched()

    assert "pydantic 2.14" in output
    assert "2.12" not in output


def test_an_older_version_is_searched_when_named(corpus: Path):
    output = searched("--version", "2.12")

    assert "pydantic 2.12" in output
    assert "2.14" not in output


def test_two_versions_show_an_unchanged_passage_once_labelled_with_both(
    corpus: Path,
):
    output = searched("--version", "all")

    assert output.count("pydantic 2.12, 2.14") == 1
    # The passage that differs is shown in each version.
    assert "the Config class" in output and "model_config" in output
    assert output.count(SAME[:30]) == 1


def test_a_version_nothing_holds_is_refused_at_the_command_line(corpus: Path):
    result = CliRunner().invoke(
        main, ["search", "validators", "--collection", "docs", "--version", "3.0"]
    )

    assert result.exit_code != 0
    assert "2.12" in result.output and "2.14" in result.output


def test_an_agent_sees_the_current_version_alone(corpus: Path):
    """The agent's search is not the sweep, and once kept every version."""
    from kennis.mcp.tools.search import search_docs

    answer = search_docs("validators", top_k=10)

    assert "pydantic 2.14" in answer
    assert "2.12" not in answer


def test_merging_does_not_cost_a_changed_passage_its_place(corpus: Path):
    """Asked for three, the search found the unchanged passage twice and
    merged it, leaving two - and the changed passage in the older version,
    the one a reader searching both wants, ranked fourth and went unshown.
    Found in a screenshot, not by the test above, which asked for ten."""
    result = CliRunner().invoke(
        main,
        ["search", "validators", "--collection", "docs", "-k", "3", "--version", "all"],
    )

    assert result.exit_code == 0, result.output
    assert "the Config class" in result.output
    assert "model_config" in result.output
    assert result.output.count("pydantic 2.12, 2.14") == 1
