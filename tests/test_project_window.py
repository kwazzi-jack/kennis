"""A project managed from the window as from the command line (2026-11-04).

The packs a project uses, its index, a reset, a new project, and Clear
history asked first. Each test submits the form the page drew (#432).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import (
    declare_packs,
    declared_packs,
    index_root_for,
    init_bundle,
)
from kennis.engine.context.projects import forget_project, known_projects
from kennis.gui import history
from kennis.gui.app import build_app
from test_pack_contents import a_provider

TOKEN = "t" * 32


@pytest.fixture(autouse=True)
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    initialised = CliRunner().invoke(main, ["corpus", "init"])
    assert initialised.exit_code == 0, initialised.output
    provider = a_provider(tmp_path / "provider")
    installed = CliRunner().invoke(main, ["pack", "install", str(provider)])
    assert installed.exit_code == 0, installed.output
    return tmp_path / "corpus"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project called boepie whose bundle holds one note of its own."""
    folder = tmp_path / "boepie"
    (folder / ".git").mkdir(parents=True)
    monkeypatch.chdir(folder)
    for arguments in (
        ["context", "init"],
        ["remember", "--context", "Calibration runs in four-minute chunks."],
    ):
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 0, result.output
    return folder


def opened() -> tuple[TestClient, FastAPI]:
    app = build_app(TOKEN)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client, app


def page_of(client: TestClient, address: str) -> BeautifulSoup:
    return BeautifulSoup(client.get(address).text, "html.parser")


def fields_of(form: Tag, **typed: str) -> dict[str, list[str]]:
    """What a browser sends for the form as drawn: hidden fields, text
    fields (or what `typed` puts in them), and only the checked checkboxes."""
    sent: dict[str, list[str]] = {}
    for field in form.select("input[name]"):
        name = str(field["name"])
        kind = field.get("type", "text")
        if kind == "checkbox" and not field.has_attr("checked"):
            continue
        value = typed.get(name, str(field.get("value", "")))
        sent.setdefault(name, []).append(value)
    return sent


def finished(client: TestClient, app: FastAPI, location: str) -> BeautifulSoup:
    assert location.startswith("/job/")
    assert app.state.jobs.get(location.removeprefix("/job/")).done.wait(20)
    return page_of(client, location)


def project_menu(client: TestClient, name: str) -> Tag:
    pane = page_of(client, "/").select_one("nav.pane")
    for row in pane.select("li.project"):
        if row.select_one(".name") and row.select_one(".name").get_text() == name:
            menu = row.select_one("details.menu")
            assert menu is not None
            return menu
    raise AssertionError(f"no row for {name}")


# ---------------------------------------------------------------------------
# The packs a project uses


def test_the_packs_dialog_declares_exactly_what_is_checked(project: Path):
    client, _ = opened()
    entry = project_menu(client, "boepie").select_one(
        "a[href='/projects/packs?project=boepie']"
    )
    assert entry is not None
    dialog = page_of(client, str(entry["href"]))
    form = dialog.select_one("form.packs")
    box = form.select_one("input[type=checkbox][value=alpha]")
    assert box is not None and not box.has_attr("checked")

    box["checked"] = ""
    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    assert declared_packs(project / ".context") == ("alpha",)
    again = page_of(client, str(entry["href"])).select_one("form.packs")
    unchecked = again.select_one("input[value=alpha]")
    del unchecked["checked"]
    client.post(str(again["action"]), data=fields_of(again))
    assert declared_packs(project / ".context") == ()


def test_a_declared_pack_not_installed_here_is_kept(project: Path):
    """The declaration is committed with the project, so a collaborator's
    pack this machine lacks must survive a save from this window."""
    declare_packs(project / ".context", ["gone"])
    client, _ = opened()
    dialog = page_of(client, "/projects/packs?project=boepie")
    form = dialog.select_one("form.packs")
    kept = form.select_one("input[type=checkbox][value=gone]")
    assert kept is not None and kept.has_attr("checked")
    assert "not installed here" in " ".join(dialog.get_text().split())

    client.post(str(form["action"]), data=fields_of(form))

    assert declared_packs(project / ".context") == ("gone",)


# ---------------------------------------------------------------------------
# Its index, and a reset


def test_indexing_a_project_from_its_menu_builds_its_index(project: Path):
    client, app = opened()
    form = project_menu(client, "boepie").select_one("form.index-project")
    assert form is not None

    answer = client.post(str(form["action"]), data=fields_of(form))

    assert answer.status_code == 303
    outcome = finished(client, app, answer.headers["location"])
    assert "Indexed" in outcome.get_text()
    assert index_root_for(project / ".context").is_dir()


def test_a_reset_lists_what_goes_and_keeps_the_person_s_files(project: Path):
    assert CliRunner().invoke(main, ["context", "index"]).exit_code == 0
    (note,) = [
        path
        for path in (project / ".context").rglob("*.md")
        if "four-minute" in path.read_text(encoding="utf-8")
    ]
    client, app = opened()
    entry = project_menu(client, "boepie").select_one(
        "a[href='/projects/reset?project=boepie']"
    )
    assert entry is not None
    dialog = page_of(client, str(entry["href"]))
    form = dialog.select_one("form.reset")
    button = form.select_one("button[type=submit]")
    assert "danger" in button.get("class", [])
    assert "index" in " ".join(dialog.get_text().split())

    answer = client.post(str(form["action"]), data=fields_of(form))

    outcome = finished(client, app, answer.headers["location"])
    assert "Removed" in outcome.get_text()
    assert not index_root_for(project / ".context").exists()
    assert note.is_file()


def test_a_reset_with_nothing_to_remove_offers_no_button(project: Path):
    client, _ = opened()
    dialog = page_of(client, "/projects/reset?project=boepie")

    assert dialog.select_one("form.reset") is None
    assert "nothing to remove" in dialog.get_text()


def test_a_missing_project_has_none_of_these_entries(project: Path):
    import shutil

    shutil.rmtree(project / ".context")
    client, _ = opened()
    menu = project_menu(client, "boepie")

    assert menu.select_one("a[href^='/projects/packs']") is None
    assert menu.select_one("a[href^='/projects/reset']") is None
    assert menu.select_one("form.index-project") is None


# ---------------------------------------------------------------------------
# A new project


def new_project_form(client: TestClient) -> Tag:
    pane = page_of(client, "/").select_one("nav.pane")
    button = pane.select_one("a.button[href='/projects/new']")
    assert button is not None and button.select_one("svg") is not None
    form = page_of(client, str(button["href"])).select_one("form.new-project")
    assert form is not None
    return form


def test_a_folder_without_a_context_gets_one_and_is_listed(tmp_path: Path):
    folder = tmp_path / "fresh"
    folder.mkdir()
    client, _ = opened()
    form = new_project_form(client)
    answer = client.post(str(form["action"]), data=fields_of(form, folder=str(folder)))

    assert answer.status_code == 303
    assert (folder / ".context" / "bundle.json").is_file()
    assert "fresh" in [one.name for one in known_projects()]


def test_a_folder_with_a_context_is_listed_and_left_alone(tmp_path: Path):
    folder = tmp_path / "kept"
    (folder / ".git").mkdir(parents=True)
    bundle = init_bundle(folder).path
    forget_project("kept")
    landing = (bundle / "LANDING.md").read_text(encoding="utf-8")
    client, _ = opened()
    form = new_project_form(client)

    client.post(str(form["action"]), data=fields_of(form, folder=str(folder)))

    assert "kept" in [one.name for one in known_projects()]
    assert (bundle / "LANDING.md").read_text(encoding="utf-8") == landing


def test_a_folder_that_is_not_there_is_refused_in_the_dialog(tmp_path: Path):
    client, _ = opened()
    form = new_project_form(client)

    answer = client.post(
        str(form["action"]),
        data=fields_of(form, folder=str(tmp_path / "nowhere")),
        headers={"HX-Request": "true"},
    )

    assert "nowhere" in answer.text
    assert not (tmp_path / "nowhere").exists()
    assert known_projects() == ()


# ---------------------------------------------------------------------------
# Clear history


def test_clear_history_asks_first(corpus: Path):
    history.record("gains", scope="notes", hits=1, capped=False, mode="")
    client, _ = opened()
    assert history.recent() != []
    recents = page_of(client, "/")
    trigger = recents.select_one("#recents a.button.danger[href='/history/clear']")
    assert trigger is not None

    dialog = page_of(client, "/history/clear")
    assert history.recent() != []
    form = dialog.select_one("form.clear-history")
    assert "danger" in form.select_one("button[type=submit]").get("class", [])

    answer = client.post(str(form["action"]))

    assert answer.status_code == 303
    assert history.recent() == []


def test_choosing_the_context_folder_itself_lists_it_without_nesting_one(
    tmp_path: Path,
):
    folder = tmp_path / "chosen"
    (folder / ".git").mkdir(parents=True)
    bundle = init_bundle(folder).path
    forget_project("chosen")
    client, _ = opened()
    form = new_project_form(client)

    client.post(str(form["action"]), data=fields_of(form, folder=str(bundle)))

    assert not (bundle / ".context").exists()
    assert [one.bundle for one in known_projects()] == [bundle.resolve()]
