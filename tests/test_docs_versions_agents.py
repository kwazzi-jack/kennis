"""An agent names docs versions as a person does (#489, unit V5).

`search_docs` takes `version` in the command line's forms, `list_corpus`
says which versions of each project are held and which is current, and
the instructions block says that a docs search covers the current version
unless told otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.errors import InputError
from kennis.mcp.instructions import instructions_for
from kennis.mcp.server import build_server
from kennis.mcp.tools.corpus import list_corpus
from kennis.mcp.tools.search import search_docs

SAME = "Validators run after parsing and may raise a ValueError."


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for version in ("2.12", "2.14"):
        source = tmp_path / version / "models.md"
        source.parent.mkdir()
        source.write_text(
            f"# Models\n\n## Validation\n\n{SAME}\n\n## Configuration\n\n"
            f"Configuration lives in setting {version}, which sets validators.\n",
            encoding="utf-8",
        )
        adding = ["corpus", "add", "-d", "--project", "pydantic", "--version"]
        result = run.invoke(main, [*adding, version, str(source)])
        assert result.exit_code == 0, result.output
    assert run.invoke(main, ["corpus", "index", "--collection", "docs"]).exit_code == 0
    return tmp_path / "corpus"


def labels_in(answer: str) -> set[str]:
    """The version label each hit's detail line carries, as one of the
    line's fields - which are joined by two spaces (#380)."""
    return {
        field
        for line in answer.splitlines()
        if line.startswith("  ")
        for field in line.strip().split("  ")
        if field.startswith("pydantic ")
    }


def test_an_agent_searches_the_current_version_by_default(corpus: Path):
    assert labels_in(search_docs("validators", top_k=10)) == {"pydantic 2.14"}


def test_an_agent_names_another_version(corpus: Path):
    answer = search_docs("validators", top_k=10, version=["pydantic=2.12"])

    assert labels_in(answer) == {"pydantic 2.12"}


def test_an_agent_searching_every_version_sees_one_copy_of_an_equal_passage(
    corpus: Path,
):
    answer = search_docs("validators", top_k=10, version=["all"])

    assert "pydantic 2.12, 2.14" in labels_in(answer)
    assert answer.count(SAME[:30]) <= 1


def test_a_version_not_held_is_an_error_naming_the_ones_that_are(corpus: Path):
    with pytest.raises(InputError) as raised:
        search_docs("validators", version=["9.9"])

    assert "2.12" in str(raised.value) and "2.14" in str(raised.value)


def test_the_published_schema_offers_version_as_a_list_of_strings(corpus: Path):
    async def listed() -> dict[str, object]:
        tools = await build_server().list_tools()
        found = next(tool for tool in tools if tool.name == "search_docs")
        return found.parameters

    schema = asyncio.run(listed())
    properties = schema["properties"]
    assert isinstance(properties, dict)
    offered = str(properties["version"])
    assert "'array'" in offered and "'string'" in offered
    required = schema.get("required", [])
    assert isinstance(required, list)
    assert "version" not in required


def test_list_corpus_says_each_projects_versions_and_the_current_one(corpus: Path):
    answer = list_corpus("docs")

    assert "pydantic: 2.12  2.14 (current)" in answer


def test_the_instructions_say_how_to_name_a_version(corpus: Path):
    said = instructions_for(())

    assert "current version" in said
    assert "version=" in said
