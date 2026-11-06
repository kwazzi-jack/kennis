"""Deleting a project's context bundle, from the command line and the window.

Forget takes a project off kennis's list and leaves its folder; delete
removes the `.context/` folder as well, which kennis cannot undo, so both
front ends ask first and say what goes (Brian, 2026-11-04).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import init_bundle
from kennis.engine.context.deleting import delete_project, what_deleting_removes
from kennis.engine.context.projects import (
    add_project,
    forget_project,
    known_projects,
)
from kennis.engine.errors import BundleNotDeletable, ContextNotFound
from kennis.gui.app import build_app

TOKEN = "t" * 32


@pytest.fixture(autouse=True)
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    initialised = CliRunner().invoke(main, ["corpus", "init"])
    assert initialised.exit_code == 0, initialised.output
    return tmp_path / "corpus"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project called boepie with a bundle holding one note of its own and
    an index, and a file of the project's beside the bundle."""
    folder = tmp_path / "boepie"
    (folder / ".git").mkdir(parents=True)
    (folder / "README.md").write_text("The project's own.\n", encoding="utf-8")
    monkeypatch.chdir(folder)
    for arguments in (
        ["context", "init"],
        ["remember", "--context", "Calibration runs in four-minute chunks."],
        ["context", "index"],
    ):
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 0, result.output
    return folder


def names() -> list[str]:
    return [one.name for one in known_projects()]


def files_outside_the_index(bundle: Path) -> int:
    return sum(
        1
        for path in bundle.rglob("*")
        if path.is_file() and ".index" not in path.relative_to(bundle).parts
    )


# ---------------------------------------------------------------------------
# The engine


def test_deleting_removes_the_bundle_and_unlists_it_and_nothing_else(
    project: Path,
):
    bundle = project / ".context"
    counted = files_outside_the_index(bundle)

    deletion = delete_project("boepie")

    assert not bundle.exists()
    assert "boepie" not in names()
    assert (project / "README.md").is_file()
    # The derived index is not counted as the person's files.
    assert deletion.files == counted
    assert deletion.project.bundle == bundle.resolve()


def test_the_preview_counts_what_the_delete_removes(project: Path):
    bundle = project / ".context"

    preview = what_deleting_removes("boepie")

    assert preview.files == files_outside_the_index(bundle)
    assert bundle.is_dir()
    assert "boepie" in names()


def test_a_project_whose_bundle_is_gone_is_refused_naming_forget(project: Path):
    import shutil

    shutil.rmtree(project / ".context")

    with pytest.raises(ContextNotFound) as refused:
        delete_project("boepie")

    assert refused.value.resolution == "kennis context forget boepie"


def test_a_listed_folder_not_called_context_is_never_deleted(tmp_path: Path):
    """A list entry is a path kennis read from a file, so a delete is aimed
    only at a folder that is a bundle by its name and its manifest."""
    folder = tmp_path / "elsewhere"
    (folder / ".git").mkdir(parents=True)
    bundle = init_bundle(folder).path
    for listed in names():
        forget_project(listed)
    kept = bundle.rename(folder / "kept")
    add_project(kept)
    (name,) = names()

    with pytest.raises(BundleNotDeletable):
        delete_project(name)

    assert (kept / "bundle.json").is_file()
    assert name in names()


# ---------------------------------------------------------------------------
# The command line


def test_context_delete_asks_and_a_no_keeps_everything(project: Path):
    result = CliRunner().invoke(main, ["context", "delete", "boepie"], input="n\n")

    assert result.exit_code != 0
    # The question names the folder and what is in it.
    assert ".context" in result.output
    assert "files?" in result.output
    assert (project / ".context").is_dir()
    assert "boepie" in names()


def test_context_delete_with_yes_deletes(project: Path):
    result = CliRunner().invoke(main, ["context", "delete", "boepie", "-y"])

    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output
    assert not (project / ".context").exists()
    assert "boepie" not in names()


# ---------------------------------------------------------------------------
# The window


def opened() -> tuple[TestClient, FastAPI]:
    app = build_app(TOKEN)
    client = TestClient(app, follow_redirects=False)
    assert client.get("/", params={"token": TOKEN}).status_code == 200
    return client, app


def finished(client: TestClient, app: FastAPI, location: str) -> BeautifulSoup:
    """The task page a plain form's POST was sent to, once its task ended."""
    assert location.startswith("/job/")
    assert app.state.jobs.get(location.removeprefix("/job/")).done.wait(20)
    return BeautifulSoup(client.get(location).text, "html.parser")


def test_deleting_from_the_window_asks_then_removes_the_folder(project: Path):
    client, app = opened()
    pane = BeautifulSoup(client.get("/").text, "html.parser").select_one("nav.pane")
    delete = pane.select_one("a[href='/projects/delete?project=boepie']")
    assert delete is not None
    # Its own entry beside Forget: one action, one role.
    assert pane.select_one("a[href='/projects/forget?project=boepie']") is not None

    dialog = BeautifulSoup(client.get(str(delete["href"])).text, "html.parser")
    form = dialog.select_one("form.delete")
    fields = {
        field["name"]: field["value"] for field in form.select("input[type=hidden]")
    }
    said = " ".join(dialog.get_text().split())
    assert str(project / ".context") in said
    assert "cannot be undone" in said

    answer = client.post(str(form["action"]), data=fields)

    assert answer.status_code == 303
    page = finished(client, app, answer.headers["location"])
    assert "Deleted" in page.get_text()
    assert not (project / ".context").exists()
    assert (project / "README.md").is_file()
    pane = BeautifulSoup(client.get("/").text, "html.parser").select_one("nav.pane")
    assert pane.select_one("a[href='/projects/delete?project=boepie']") is None


def test_deleting_a_project_not_known_is_a_problem_page(project: Path):
    client, _ = opened()

    assert (
        client.get("/projects/delete", params={"project": "nobody"}).status_code == 404
    )
    assert (
        client.post("/projects/delete", data={"project": "nobody"}).status_code == 404
    )
    assert (project / ".context").is_dir()


# ---------------------------------------------------------------------------
# A removal looks like one


TEMPLATES = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "templates"

# Written by hand: every control whose action removes something. Its button
# wears the removal colour and a trash icon, so it reads as a removal before
# its words are read (Brian, 2026-11-04). Forget and Return remove nothing:
# a forgotten project is listed again, and a return is its own commit.
REMOVING = {
    "forms/delete-project.html",
    "forms/remove-document.html",
    "forms/remove-version.html",
    "forms/uninstall-pack.html",
    "forms/clear-history.html",
    "forms/reset-project.html",
}


def submit_buttons(template: str) -> list[str]:
    import re

    source = (TEMPLATES / template).read_text(encoding="utf-8")
    return re.findall(r"<button[^>]*type=\"submit\"[^>]*>.*?</button>", source)


@pytest.mark.parametrize("template", sorted(REMOVING))
def test_a_control_that_removes_is_drawn_as_a_removal(template: str):
    (button,) = submit_buttons(template)

    assert 'class="danger' in button or " danger" in button
    assert 'icon("trash-2")' in button


def test_no_other_control_is_drawn_as_a_removal():
    drawn = {
        path.relative_to(TEMPLATES).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if any(
            "danger" in button
            for button in submit_buttons(path.relative_to(TEMPLATES).as_posix())
        )
    }

    assert drawn == REMOVING


# ---------------------------------------------------------------------------
# A project whose folder has gone


def test_a_missing_project_is_listed_with_forget_alone(project: Path):
    import shutil

    shutil.rmtree(project / ".context")
    client, _ = opened()
    page = BeautifulSoup(client.get("/").text, "html.parser")
    pane = page.select_one("nav.pane")

    row = pane.select_one("li.project.missing")
    assert row is not None
    assert "boepie" in row.get_text()
    assert row.select_one("a[href='/projects/forget?project=boepie']") is not None
    assert row.select_one("a[href^='/projects/delete']") is None
    # Nothing to open: the folder is gone.
    assert row.select_one("details[hx-get]") is None

    dialog = BeautifulSoup(
        client.get("/projects/forget", params={"project": "boepie"}).text,
        "html.parser",
    )
    said = " ".join(dialog.get_text().split())
    assert "is not there" in said
    assert "Its files stay" not in said
