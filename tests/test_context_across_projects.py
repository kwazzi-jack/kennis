"""A search across the machine's projects (14g, #512).

The command line and an agent search the project they stand in, and every
known project when asked; the window searches every known project and does
not depend on where it was started. Each project's notes are their own
group, because each index has its own scale; a pack declared by several
projects is searched once.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import declare_packs, init_bundle
from kennis.engine.context.index import index_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.context.projects import ProjectNotKnown
from kennis.engine.pack.update import update_pack
from kennis.gui.app import build_app
from kennis.mcp.tools.search import search_context
from kennis.retrieval import sweep


@pytest.fixture(autouse=True)
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    answered = CliRunner().invoke(main, ["corpus", "init"])
    assert answered.exit_code == 0, answered.output
    return root


def a_project(root: Path, note: str | None = None) -> Path:
    """A project with a bundle and, when given, one indexed note."""
    (root / ".git").mkdir(parents=True)
    bundle = init_bundle(root).path
    if note is not None:
        remember_in_bundle(bundle, note, title=None, group=None)
        index_bundle(bundle)
    return bundle


@pytest.fixture
def two(tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`pipelines`, the working directory, and `thesis`, elsewhere; both
    write about gains. Returns the thesis bundle."""
    here = a_project(tmp_path / "pipelines", "Pipelines solve the gains per scan.")
    monkeypatch.chdir(here.parent)
    return a_project(tmp_path / "thesis", "The thesis smooths the gains in time.")


def installed(tmp_path: Path, identifier: str = "alpha") -> None:
    root = tmp_path / "providers" / identifier
    if root.exists():
        shutil.rmtree(root)
    (root / "content").mkdir(parents=True)
    (root / "content" / "solving.md").write_text(
        "Solve the gains per scan.\n", encoding="utf-8"
    )
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    update_pack(path)
    answered = CliRunner().invoke(main, ["pack", "add", str(path)])
    assert answered.exit_code == 0, answered.output


def groups_of(bundle: Path | None, others: list[Path]) -> dict[str, list[str]]:
    found = sweep(
        "gains", scopes=["context"], named=False, bundle=bundle, others=others
    )
    return {
        name: [hit.result.chunk.document_id for hit in hits]
        for name, hits in found.groups.items()
    }


# ---------------------------------------------------------------------------
# The sweep


def test_this_project_alone_is_searched_unless_others_are_named(two: Path):
    here = Path.cwd() / ".context"

    assert set(groups_of(here, [])) == {"context"}


def test_each_other_project_is_its_own_group_by_its_name(two: Path):
    here = Path.cwd() / ".context"

    assert set(groups_of(here, [two])) == {"context", "context:thesis"}


def test_with_no_project_of_its_own_every_project_is_named(two: Path):
    """The window's case: it was started nowhere in particular."""
    here = Path.cwd() / ".context"

    assert set(groups_of(None, [here, two])) == {
        "context:pipelines",
        "context:thesis",
    }


def test_a_hit_in_another_project_says_where_the_file_is(two: Path):
    """`.context/...` would name a file in this project, which is wrong."""
    from kennis.render.hits import hit_detail

    found = sweep(
        "smooths",
        scopes=["context"],
        named=False,
        bundle=Path.cwd() / ".context",
        others=[two],
    )
    (hit,) = found.groups["context:thesis"]

    assert f"path={two}/" in hit_detail(hit, style="none", best=1.0)


def test_a_pack_two_projects_declare_is_searched_once(two: Path, tmp_path: Path):
    here = Path.cwd() / ".context"
    installed(tmp_path)
    declare_packs(here, ["alpha"])
    declare_packs(two, ["alpha"])

    groups = groups_of(None, [here, two])

    assert groups["pack:alpha"] == ["solving.md"]


def test_one_project_s_copy_does_not_hide_the_pack_from_another(
    two: Path, tmp_path: Path
):
    here = Path.cwd() / ".context"
    installed(tmp_path)
    declare_packs(here, ["alpha"])
    declare_packs(two, ["alpha"])
    answered = CliRunner().invoke(main, ["context", "copy", "alpha/solving.md"])
    assert answered.exit_code == 0, answered.output

    assert "pack:alpha" not in groups_of(here, [])
    assert groups_of(here, [two])["pack:alpha"] == ["solving.md"]


def test_an_unindexed_other_project_names_the_command_for_it(two: Path, tmp_path: Path):
    """Run as printed, from wherever the reader is."""
    other = a_project(tmp_path / "survey")
    remember_in_bundle(other, "Survey gains.", title=None, group=None)

    found = sweep(
        "gains",
        scopes=["context"],
        named=False,
        bundle=Path.cwd() / ".context",
        others=[two, other],
    )

    (skipped,) = found.skipped
    assert skipped.name == "context:survey"
    assert skipped.resolution == "kennis context index --project survey"


# ---------------------------------------------------------------------------
# The command line


def test_search_reads_this_project_only_by_default(two: Path):
    answered = CliRunner().invoke(main, ["search", "gains"])

    assert answered.exit_code == 0, answered.output
    assert "Pipelines solve" in answered.output
    assert "thesis smooths" not in answered.output


def test_search_all_projects_reads_every_known_project(two: Path):
    answered = CliRunner().invoke(main, ["search", "gains", "--all-projects"])

    assert answered.exit_code == 0, answered.output
    assert "Context thesis" in answered.output
    assert "thesis smooths" in answered.output


def test_search_all_projects_outside_any_project(
    two: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    answered = CliRunner().invoke(main, ["search", "gains", "--all-projects"])

    assert answered.exit_code == 0, answered.output
    assert "thesis smooths" in answered.output


def test_context_index_project_indexes_another_project(two: Path):
    remember_in_bundle(two, "A second note on gains.", title=None, group=None)

    answered = CliRunner().invoke(main, ["context", "index", "--project", "thesis"])

    assert answered.exit_code == 0, answered.output
    assert "2 documents" in answered.output


def test_context_index_project_refuses_an_unknown_name(two: Path):
    answered = CliRunner().invoke(main, ["context", "index", "--project", "nope"])

    assert answered.exit_code != 0
    assert "kennis context list" in answered.output


# ---------------------------------------------------------------------------
# An agent


def test_an_agent_searches_its_own_project_by_default(two: Path):
    answered = search_context("gains")

    assert "path=.context/" in answered
    assert str(two) not in answered


def test_an_agent_may_search_every_project(two: Path):
    answered = search_context("smooths", projects="all")

    assert f"path={two}/" in answered


def test_an_agent_may_name_projects(two: Path):
    answered = search_context("smooths", projects=["thesis"])

    assert f"path={two}/" in answered


def test_an_agent_naming_an_unknown_project_is_refused(two: Path):
    with pytest.raises(ProjectNotKnown):
        search_context("gains", projects=["nope"])


def test_an_agent_outside_any_project_searches_every_project(
    two: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    answered = search_context("smooths")

    assert f"path={two}/" in answered


# ---------------------------------------------------------------------------
# The window, which belongs to no project (#512)


TOKEN = "a-test-token"


@pytest.fixture
def window(two: Path) -> TestClient:
    """The window, opened with no project named."""
    client = TestClient(build_app(TOKEN), follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client


def group_names(answer: str) -> list[str]:
    page = BeautifulSoup(answer, "html.parser")
    return [
        name.get_text()
        for name in page.select("h2.group-head .name")
        if name is not None
    ]


def test_the_window_searches_every_project(window: TestClient):
    found = window.get("/hits", params={"q": "gains", "scope": "context"})

    assert group_names(found.text) == ["context pipelines", "context thesis"]


def test_the_window_filters_to_one_project(window: TestClient):
    found = window.get(
        "/hits", params={"q": "gains", "scope": "context", "project": "thesis"}
    )

    assert group_names(found.text) == ["context thesis"]


def test_the_filter_is_offered_once_two_projects_are_known(window: TestClient):
    page = BeautifulSoup(window.get("/").text, "html.parser")
    choice = page.select_one("select[name=project]")

    assert choice is not None
    values = [str(option.get("value")) for option in choice.select("option")]
    assert values == ["", "pipelines", "thesis"]


def test_a_project_s_hit_leads_to_its_note(window: TestClient):
    found = window.get(
        "/hits", params={"q": "smooths", "scope": "context", "project": "thesis"}
    )
    page = BeautifulSoup(found.text, "html.parser")
    link = page.select_one("li.hit a.title")
    assert link is not None

    note = window.get(str(link["href"]))

    assert note.status_code == 200
    assert "The thesis smooths" in BeautifulSoup(note.text, "html.parser").get_text()


def test_the_pane_lists_every_project_and_each_opens_its_notes(window: TestClient):
    page = BeautifulSoup(window.get("/").text, "html.parser")
    rows = [
        str(row["hx-get"]) for row in page.select("details[hx-get^='/tree/context']")
    ]
    assert rows == [
        "/tree/context?project=pipelines",
        "/tree/context?project=thesis",
    ]

    tree = BeautifulSoup(window.get(rows[1]).text, "html.parser")
    links = [str(link["href"]) for link in tree.select("a.leaf")]
    assert links and all(link.endswith("?project=thesis") for link in links)
    assert window.get(links[0]).status_code == 200


def test_the_window_keeps_no_project_from_where_it_was_opened(window: TestClient):
    """The bundle parameter and cookie of #508 are gone: the window is the
    same whichever project `kennis gui` was typed in."""
    answer = window.get("/", params={"bundle": str(Path.cwd() / ".context")})

    assert "kennis-bundle" not in answer.headers.get("set-cookie", "")
    found = window.get("/hits", params={"q": "gains", "scope": "context"})
    assert group_names(found.text) == ["context pipelines", "context thesis"]


def test_a_note_can_be_written_into_any_project(window: TestClient, two: Path):
    page = BeautifulSoup(window.get("/remember").text, "html.parser")
    targets = [str(choice["value"]) for choice in page.select("input[name=target]")]
    assert targets == ["notes", "context:pipelines", "context:thesis"]

    answer = window.post(
        "/remember",
        data={"text": "Written from the window.", "target": "context:thesis"},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200
    assert any(
        "Written from the window." in path.read_text(encoding="utf-8")
        for path in two.glob("*.md")
    )


def test_the_window_offers_no_context_sync(window: TestClient):
    """A sync only clears copies earlier versions made; it is run on the
    command line, in the project concerned (14g)."""
    page = window.get("/sync")

    assert "/context-sync" not in page.text


def test_a_plain_context_target_is_refused_even_beside_a_project_called_context(
    window: TestClient, tmp_path: Path
):
    """`context` alone is what the form sent when the window had one
    project; a project that happens to be called `context` must not
    receive what was meant for another."""
    called_context = a_project(tmp_path / "context")

    answer = window.post(
        "/remember",
        data={"text": "Meant for elsewhere.", "target": "context"},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200
    assert not any(
        "Meant for elsewhere." in path.read_text(encoding="utf-8")
        for path in called_context.glob("*.md")
    )


def test_more_from_a_project_or_a_pack_asks_for_a_scope_the_window_has(
    window: TestClient,
):
    """`scope=pack:alpha` or `scope=context:thesis` would be refused as an
    unknown scope; both are the context scope, a project's narrowed."""
    from kennis.gui.routes.search import scope_query

    assert scope_query("context:old/thesis") == "scope=context&project=old/thesis"
    assert scope_query("pack:alpha") == "scope=context"
    assert scope_query("notes") == "scope=notes"
    answer = window.get(f"/hits?q=gains&{scope_query('context:thesis')}")
    assert group_names(answer.text) == ["context thesis"]


def test_the_filter_is_kept_in_the_address(window: TestClient):
    """So a reload, Back or a shared link searches the same project."""
    answer = window.get(
        "/hits", params={"q": "gains", "scope": "context", "project": "thesis"}
    )

    assert "&project=thesis" in answer.headers["HX-Push-Url"]
