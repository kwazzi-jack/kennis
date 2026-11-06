"""A pack's context, copied into the project and searched as the project's
own (Brian, 2026-11-06, #624, reversing #513).

What crosses the front ends: `kennis context sync` copies and reports,
`--remove-undeclared` is the deliberate removal, `context packs` declares
and names the sync, `context copy` is gone, a search has no `pack:` group,
and the window syncs a project from its menu.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import declare_packs, declared_packs, init_bundle
from kennis.engine.pack.update import update_pack
from kennis.gui.app import build_app
from kennis.retrieval import sweep

TOKEN = "t" * 32


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


@pytest.fixture
def project(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project called pipelines, the working directory of every test,
    with the pack alpha installed on the machine."""
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    init_bundle(root)
    monkeypatch.chdir(root)
    installed(tmp_path)
    return root / ".context"


def installed(tmp_path: Path, identifier: str = "alpha") -> None:
    root = tmp_path / "providers" / identifier
    if root.exists():
        shutil.rmtree(root)
    (root / "content").mkdir(parents=True)
    (root / "content" / "solving.md").write_text(
        "---\ntitle: Solving\n---\nSolve the gains per scan.\n", encoding="utf-8"
    )
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    update_pack(path)
    answered = CliRunner().invoke(main, ["pack", "install", str(path)])
    assert answered.exit_code == 0, answered.output


def run(*arguments: str) -> str:
    answered = CliRunner().invoke(main, list(arguments))
    assert answered.exit_code == 0, answered.output
    return " ".join(answered.output.split())


# ---------------------------------------------------------------------------
# The command line


def test_sync_copies_a_declared_pack_s_file_and_says_so(project: Path):
    declare_packs(project, ["alpha"])

    said = run("context", "sync")

    assert (project / "solving.md").is_file()
    assert "solving.md" in said
    assert "1 file written" in said


def test_declaring_a_pack_names_the_sync_that_copies_it(project: Path):
    said = run("context", "packs", "alpha")

    assert declared_packs(project) == ("alpha",)
    assert not (project / "solving.md").exists()
    assert "kennis context sync" in said


def test_a_dropped_pack_s_files_stay_until_the_sync_is_asked_to_remove_them(
    project: Path,
):
    declare_packs(project, ["alpha"])
    run("context", "sync")
    run("context", "packs", "--drop", "alpha")

    kept = run("context", "sync")
    assert (project / "solving.md").is_file()
    assert "kennis context sync --remove-undeclared" in kept

    run("context", "sync", "--remove-undeclared")
    assert not (project / "solving.md").exists()


def test_there_is_no_context_copy_command(project: Path):
    answered = CliRunner().invoke(main, ["context", "copy", "alpha/solving.md"])

    assert answered.exit_code != 0
    assert "No such command" in answered.output


# ---------------------------------------------------------------------------
# Searching


def test_a_pack_s_copy_is_searched_as_the_project_s_own(project: Path):
    declare_packs(project, ["alpha"])
    run("context", "sync")
    run("context", "index")

    found = sweep("gains", scopes=["context"], named=False, bundle=project)

    assert {
        name: [hit.result.chunk.document_id for hit in hits]
        for name, hits in found.groups.items()
    } == {"context": ["solving.md"]}
    said = run("search", "gains", "--collection", "context")
    assert "path=.context/solving.md" in said
    assert "pack=" not in said


def test_a_declared_pack_is_not_searched_until_it_is_synced(project: Path):
    declare_packs(project, ["alpha"])
    (project / "mine.md").write_text(
        "---\ntitle: Mine\n---\nOur gains drift.\n", encoding="utf-8"
    )
    run("context", "index")

    found = sweep("gains", scopes=["context"], named=False, bundle=project)

    assert [hit.result.chunk.document_id for hit in found.groups["context"]] == [
        "mine.md"
    ]


# ---------------------------------------------------------------------------
# The window


def opened() -> tuple[TestClient, FastAPI]:
    app = build_app(TOKEN)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client, app


def page_of(client: TestClient, address: str) -> BeautifulSoup:
    return BeautifulSoup(client.get(address).text, "html.parser")


def fields_of(form: Tag) -> dict[str, list[str]]:
    sent: dict[str, list[str]] = {}
    for field in form.select("input[name]"):
        if field.get("type") == "checkbox" and not field.has_attr("checked"):
            continue
        sent.setdefault(str(field["name"]), []).append(str(field.get("value", "")))
    return sent


def finished(client: TestClient, app: FastAPI, location: str) -> BeautifulSoup:
    assert location.startswith("/job/")
    assert app.state.jobs.get(location.removeprefix("/job/")).done.wait(20)
    return page_of(client, location)


def sync_entry(client: TestClient) -> str:
    pane = page_of(client, "/").select_one("nav.pane")
    entry = pane.select_one("a[href='/projects/sync?project=pipelines']")
    assert entry is not None
    return str(entry["href"])


def test_the_project_menu_syncs_and_the_dialog_says_what_it_will_do(project: Path):
    declare_packs(project, ["alpha"])
    client, app = opened()
    dialog = page_of(client, sync_entry(client))
    assert "solving.md" in dialog.get_text()
    form = dialog.select_one("form.sync-project")
    assert form is not None

    answer = client.post(str(form["action"]), data=fields_of(form))

    outcome = finished(client, app, answer.headers["location"])
    assert "solving.md" in outcome.get_text()
    assert (project / "solving.md").is_file()


def test_the_dialog_removes_a_dropped_pack_s_files_only_when_ticked(project: Path):
    declare_packs(project, ["alpha"])
    run("context", "sync")
    declare_packs(project, [])
    client, app = opened()
    form = page_of(client, sync_entry(client)).select_one("form.sync-project")
    box = form.select_one("input[type=checkbox][name=remove_undeclared]")
    assert box is not None and not box.has_attr("checked")

    unticked = client.post(str(form["action"]), data=fields_of(form))
    finished(client, app, unticked.headers["location"])
    assert (project / "solving.md").is_file()

    box["checked"] = ""
    ticked = client.post(str(form["action"]), data=fields_of(form))
    finished(client, app, ticked.headers["location"])
    assert not (project / "solving.md").exists()


def test_saving_the_packs_dialog_leads_to_the_sync_dialog(project: Path):
    client, _ = opened()
    form = page_of(client, "/projects/packs?project=pipelines").select_one("form.packs")
    form.select_one("input[value=alpha]")["checked"] = ""

    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    assert answer.headers["location"] == "/projects/sync?project=pipelines"
    assert not (project / "solving.md").exists()


def test_the_window_has_no_page_for_a_pack_s_file_in_the_store(project: Path):
    client, _ = opened()

    assert client.get("/pack/alpha/solving.md").status_code == 404
