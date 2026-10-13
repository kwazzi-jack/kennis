"""Milestone 13b: the Backup section of the settings page.

Every control goes through 13a's engine: `check_backup` for what the
section says, `back_up_corpus` as a job for Back up now, and
`apply_answers` for the folder. No password is ever drawn back into a
page.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.backup import BACKUP_NAME, check_backup
from kennis.engine.errors import SettingsError
from kennis.engine.settings import load_settings
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.routes import settings as settings_routes
from kennis.render.backup import (
    BACKUP_CONTENTS,
    NO_BACKUP_FOLDER,
    describe_archive,
    describe_folder,
    describe_verified,
)

STATIC = Path(__file__).parent.parent / "src" / "kennis" / "gui" / "static"
TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}
PASSWORD = "correct horse battery staple"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    chosen = tmp_path / "Dropbox" / "kennis"
    chosen.mkdir(parents=True)
    return chosen


def code_of(name: str) -> str:
    """A script with its comment lines removed, so prose cannot satisfy a
    test about code (#373)."""
    script = (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("//")
    )


def configured(folder: Path) -> None:
    told = CliRunner().invoke(main, ["config", "set", "backup.folder", str(folder)])
    assert told.exit_code == 0, told.output


def section_of(text: str) -> Tag:
    found = BeautifulSoup(text, "html.parser").find(attrs={"data-section": "backup"})
    assert isinstance(found, Tag), text[:400]
    return found


def form_of(section: Tag, name: str) -> Tag:
    form = section.find("form", class_=name)
    assert isinstance(form, Tag), name
    return form


def finished(client: TestClient, answer_text: str) -> str:
    """Drain the stream of the job a POST started, then ask its outcome.

    The stream ends when the operation does, so reading it to the end is
    the wait, as `test_gui_manage.finished` does it.
    """
    job = BeautifulSoup(answer_text, "html.parser").find(attrs={"data-job": True})
    assert isinstance(job, Tag), answer_text[:400]
    job_id = str(job["data-job"])
    with client.stream("GET", f"/job/{job_id}/events") as answer:
        for _ in answer.iter_lines():
            pass
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        outcome = client.get(f"/job/{job_id}/outcome", headers=HTMX)
        if words.STILL_RUNNING not in outcome.text:
            return outcome.text
    raise AssertionError("the job never finished")


# ---------------------------------------------------------------------------
# What the section says
# ---------------------------------------------------------------------------


def test_the_section_says_what_the_backup_holds(client: TestClient):
    section = section_of(client.get("/settings").text)

    assert section.get("id") == "backup"
    assert BACKUP_CONTENTS in section.get_text(" ", strip=True)


def test_with_no_folder_it_says_so(client: TestClient):
    section = section_of(client.get("/settings").text)

    assert NO_BACKUP_FOLDER in section.get_text(" ", strip=True)


def test_with_a_folder_it_says_what_a_check_says(client: TestClient, folder: Path):
    configured(folder)
    text = section_of(client.get("/settings").text).get_text(" ", strip=True)
    checked = check_backup(folder)

    assert describe_folder(checked) in text
    assert describe_archive(checked) in text


def test_restoring_is_a_command_not_a_control(client: TestClient):
    section = section_of(client.get("/settings").text)
    command = section.find(
        "code", string=lambda text: bool(text) and "kennis backup restore" in text
    )

    assert command is not None
    assert (
        section.find(
            "form", attrs={"action": lambda value: bool(value) and "restore" in value}
        )
        is None
    )


def test_the_folder_field_opens_the_chooser_on_folders(client: TestClient):
    section = section_of(client.get("/settings").text)
    browse = section.find(
        attrs={"hx-get": lambda value: bool(value) and value.startswith("/browse")}
    )
    assert isinstance(browse, Tag)
    address = str(browse["hx-get"])

    assert "target=backup.folder" in address
    assert "folders=1" in address
    assert client.get(address, headers=HTMX).status_code == 200


# ---------------------------------------------------------------------------
# Choosing the folder
# ---------------------------------------------------------------------------


def test_saving_a_folder_writes_the_setting(client: TestClient, folder: Path):
    form = form_of(section_of(client.get("/settings").text), "backup-folder")

    answer = client.post(
        str(form["hx-post"]), data={"backup.folder": str(folder)}, headers=HTMX
    )

    assert answer.status_code == 200
    assert load_settings().backup.folder == str(folder)
    assert describe_folder(check_backup(folder)) in section_of(answer.text).get_text(
        " ", strip=True
    )


def test_a_file_is_not_a_folder(client: TestClient, tmp_path: Path):
    a_file = tmp_path / "notes.txt"
    a_file.write_text("x", encoding="utf-8")

    answer = client.post(
        "/settings/backup", data={"backup.folder": str(a_file)}, headers=HTMX
    )

    assert load_settings().backup.folder == ""
    folder_form = form_of(section_of(answer.text), "backup-folder")
    assert folder_form.find(class_="role-error") is not None


# ---------------------------------------------------------------------------
# Backing up
# ---------------------------------------------------------------------------


def test_back_up_now_runs_as_a_job_and_says_what_it_wrote(
    client: TestClient, folder: Path
):
    configured(folder)
    form = form_of(section_of(client.get("/settings").text), "backup-now")
    assert form["hx-post"] == form["action"] == "/backup"
    assert form["hx-target"] == "#job"

    answer = client.post(
        "/backup", data={"password": PASSWORD, "confirmation": PASSWORD}, headers=HTMX
    )
    page = finished(client, answer.text)

    assert (folder / BACKUP_NAME).is_file()
    assert str(folder / BACKUP_NAME) in page
    assert PASSWORD not in answer.text
    assert PASSWORD not in page


def test_passwords_that_differ_start_nothing(client: TestClient, folder: Path):
    configured(folder)

    answer = client.post(
        "/backup",
        data={"password": PASSWORD, "confirmation": "something else"},
        headers=HTMX,
    )

    assert words.PASSWORDS_DIFFER in answer.text
    assert list(folder.iterdir()) == []
    assert PASSWORD not in answer.text


def test_an_empty_password_starts_nothing(client: TestClient, folder: Path):
    configured(folder)

    answer = client.post(
        "/backup", data={"password": "", "confirmation": ""}, headers=HTMX
    )

    assert words.PASSWORD_NEEDED in answer.text
    assert list(folder.iterdir()) == []


def test_without_a_folder_nothing_starts(client: TestClient):
    answer = client.post(
        "/backup", data={"password": PASSWORD, "confirmation": PASSWORD}, headers=HTMX
    )

    assert NO_BACKUP_FOLDER in answer.text
    assert "data-job" not in answer.text


def test_no_password_field_is_drawn_with_a_value(client: TestClient, folder: Path):
    configured(folder)
    section = section_of(client.get("/settings").text)
    fields = section.find_all("input", attrs={"type": "password"})

    assert len(fields) == 3  # two to back up, one to test
    assert all(not field.get("value") for field in fields)


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------


def test_testing_with_the_password_says_every_file_matched(
    client: TestClient, folder: Path
):
    configured(folder)
    finished(
        client,
        client.post(
            "/backup",
            data={"password": PASSWORD, "confirmation": PASSWORD},
            headers=HTMX,
        ).text,
    )
    form = form_of(section_of(client.get("/settings").text), "backup-test")

    answer = client.post(
        str(form["hx-post"]), data={"password": PASSWORD}, headers=HTMX
    )

    assert describe_verified(True) in section_of(answer.text).get_text(" ", strip=True)
    assert PASSWORD not in answer.text


def test_testing_with_the_wrong_password_says_so_as_an_error(
    client: TestClient, folder: Path
):
    configured(folder)
    finished(
        client,
        client.post(
            "/backup",
            data={"password": PASSWORD, "confirmation": PASSWORD},
            headers=HTMX,
        ).text,
    )

    answer = client.post(
        "/settings/backup/test", data={"password": "not it"}, headers=HTMX
    )
    # Beside the control that produced it, not at the head of the section.
    problem = form_of(section_of(answer.text), "backup-test").find(class_="role-error")

    assert isinstance(problem, Tag)
    assert describe_verified(False) in problem.get_text(" ", strip=True)


def test_without_a_script_each_form_answers_with_a_page(
    client: TestClient, folder: Path
):
    answer = client.post("/settings/backup", data={"backup.folder": str(folder)})

    assert answer.status_code == 200
    assert 'class="shell"' in answer.text
    assert load_settings().backup.folder == str(folder)


def test_a_finished_backup_redraws_the_section_it_was_started_from(
    client: TestClient, folder: Path
):
    """The strip said "Backed up" while the section beside it still said
    no backup had been written, on the same page. The outcome now asks
    for the section again, but only where the page has one."""
    configured(folder)
    outcome = finished(
        client,
        client.post(
            "/backup",
            data={"password": PASSWORD, "confirmation": PASSWORD},
            headers=HTMX,
        ).text,
    )
    hook = BeautifulSoup(outcome, "html.parser").find(attrs={"data-redraw-id": True})
    assert isinstance(hook, Tag), outcome
    assert hook["data-redraw-id"] == "backup"
    assert hook["data-redraw-route"] == "/settings/backup"
    # The script is what asks, and only where the page has the element.
    code = code_of("progress.js")
    assert "document.getElementById(hook.dataset.redrawId)" in code
    assert "hook.dataset.redrawRoute" in code
    assert "redraw(outcome);" in code
    # Without this, `htmx.ajax` with no target would swap the section into
    # a page that has none. The behaviour needs a browser; the walk saw it.
    assert "if (!target || !window.htmx) { return; }" in code

    redrawn = client.get("/settings/backup", headers=HTMX)

    assert describe_archive(check_backup(folder)) in section_of(redrawn.text).get_text(
        " ", strip=True
    )
    assert "no backup has been written" not in redrawn.text


def test_without_a_script_the_section_address_is_the_page(client: TestClient):
    answer = client.get("/settings/backup")

    assert answer.status_code == 200
    assert 'class="shell"' in answer.text


# ---------------------------------------------------------------------------
# A setting that will not be written, or will not be read
# ---------------------------------------------------------------------------


def test_a_folder_the_settings_refuse_is_said_beside_the_field(
    client: TestClient, folder: Path, monkeypatch: pytest.MonkeyPatch
):
    def refused(answers: object) -> None:
        raise SettingsError("the configuration file could not be written")

    monkeypatch.setattr(settings_routes, "apply_answers", refused)

    answer = client.post(
        "/settings/backup",
        data={"backup.folder": str(folder)},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200
    assert "the configuration file could not be written" in section_of(answer.text).text


def test_a_setting_out_of_range_is_named_on_the_page_not_a_server_error(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Nearly every route reads the settings, so one value out of range in
    a hand-edited file answered every page with "Internal Server Error"."""
    configuration = tmp_path / "edited-config"
    configuration.mkdir()
    (configuration / "config.toml").write_text(
        "[retrieval]\ndefault_top_k = 0\n", encoding="utf-8"
    )
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(configuration))

    for path in ("/", "/settings", "/corpus"):
        page = client.get(path)
        assert "retrieval.default_top_k" in page.text, path
        assert "kennis config show" in page.text, path
