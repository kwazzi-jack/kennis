"""The window's setup wizard (#682, sketch 2026-11-17-setup-wizard, unit 2).

`kennis gui` with nothing set up serves the wizard itself, before any
corpus exists, rather than the corpus service, which refuses a folder
holding no corpus. Four steps, each a page: the settings, the corpus, an
agent, and the way into the window.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis import setting_up
from kennis.cli.__main__ import main
from kennis.gui import setup_app
from kennis.gui.setup_app import build_setup_app

TOKEN = "setup-token"
SERVICE = "http://127.0.0.1:9/?token=service-token"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    return tmp_path


class Recorded:
    """What the wizard asked of the world outside it."""

    def __init__(self) -> None:
        self.started: list[Path] = []
        self.done = 0
        self.claude: list[list[str]] = []
        self.registered = False

    def start(self, root: Path) -> str:
        self.started.append(root)
        return SERVICE

    def finish(self) -> None:
        self.done += 1

    def claude_code(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        self.claude.append(arguments)
        asked = arguments[:2] == ["mcp", "get"]
        code = 1 if asked and not self.registered else 0
        return subprocess.CompletedProcess(["claude", *arguments], code, "", "")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Recorded:
    recorded = Recorded()
    monkeypatch.setattr(setting_up, "claude_code", recorded.claude_code)
    monkeypatch.setattr(setting_up, "claude_on_path", lambda: True)
    monkeypatch.setattr(setting_up, "mcp_installed", lambda: True)
    return recorded


@pytest.fixture
def client(world: Recorded) -> TestClient:
    app = build_setup_app(TOKEN, start_service=world.start, on_done=world.finish)
    opened = TestClient(app, follow_redirects=False)
    # Any page sets the token's cookie; the last step's draws no settings,
    # so a defect in laying them out fails the test that reads them rather
    # than this fixture.
    answer = opened.get("/", params={"token": TOKEN, "step": "done"})
    assert answer.status_code == 200
    return opened


def page_of(client: TestClient, address: str) -> BeautifulSoup:
    answer = client.get(address)
    assert answer.status_code == 200, answer.text
    return BeautifulSoup(answer.text, "html.parser")


@dataclass(frozen=True)
class Answer:
    """What a test reads of a response: the test client's own type comes
    from `httpx2` or `httpx`, whichever is installed."""

    status_code: int
    location: str
    text: str


def submitted(client: TestClient, form: Tag, **typed: str) -> Answer:
    """The form as the page drew it: its address, and every field it holds
    with the value drawn, a select's chosen option, or what `typed` gives."""
    fields: dict[str, str] = {}
    for field in form.select("input[name], select[name], textarea[name]"):
        name = str(field["name"])
        if field.name == "select":
            chosen = field.select_one("option[selected]") or field.select_one("option")
            value = str(chosen["value"]) if chosen is not None else ""
        elif field.get("type") in ("checkbox", "radio") and not field.has_attr(
            "checked"
        ):
            continue
        else:
            value = str(field.get("value", ""))
        fields[name] = typed.get(name, value)
    for name, value in typed.items():
        fields.setdefault(name, value)
    answer = client.post(str(form["action"]), data=fields)
    return Answer(answer.status_code, answer.headers.get("location", ""), answer.text)


def form_on(page: BeautifulSoup, selector: str) -> Tag:
    form = page.select_one(selector)
    assert form is not None, f"no {selector} on the page"
    return form


def test_without_its_token_the_wizard_is_refused(world: Recorded) -> None:
    app = build_setup_app(TOKEN, start_service=world.start, on_done=world.finish)

    answer = TestClient(app, follow_redirects=False).get("/")

    assert answer.status_code == 401


def test_the_settings_posted_as_drawn_are_written_and_lead_to_the_corpus(
    client: TestClient, isolated: Path
) -> None:
    form = form_on(page_of(client, "/"), "form.setup-settings")
    assert form.select_one("[name='corpus.root']") is not None

    answer = submitted(client, form)

    assert answer.status_code == 303
    assert answer.location == "/?step=corpus"
    assert (isolated / "config" / "config.toml").is_file()


def test_a_refused_value_is_marked_beside_its_field_and_nothing_is_written(
    client: TestClient, isolated: Path
) -> None:
    form = form_on(page_of(client, "/"), "form.setup-settings")

    answer = submitted(client, form, **{"chunking.size": "5"})

    assert answer.status_code == 200
    page = BeautifulSoup(answer.text, "html.parser")
    row = page.select_one(".setting[data-key='chunking.size']")
    assert row is not None and row.select_one(".role-error") is not None
    assert not (isolated / "config" / "config.toml").exists()


def test_settings_already_written_are_kept_unless_changing_is_asked(
    client: TestClient, isolated: Path
) -> None:
    written = isolated / "config" / "config.toml"
    written.parent.mkdir(parents=True)
    written.write_text("[chunking]\nsize = 900\n", encoding="utf-8")

    page = page_of(client, "/")

    assert page.select_one("form.setup-settings") is None
    assert str(written) in page.get_text()
    onward = page.select_one("a[href='/?step=corpus']")
    assert onward is not None
    assert page_of(client, "/?step=settings&change=yes").select_one(
        "form.setup-settings"
    )


def test_create_makes_the_corpus_at_the_root_the_settings_name(
    client: TestClient, isolated: Path
) -> None:
    page = page_of(client, "/?step=corpus")
    assert str(isolated / "corpus") in page.get_text()

    answer = submitted(client, form_on(page, "form.setup-corpus"))

    assert answer.status_code == 303
    assert answer.location == "/?step=agent"
    assert (isolated / "corpus" / ".git").is_dir()
    again = page_of(client, "/?step=corpus")
    assert again.select_one("form.setup-corpus") is None


def test_claude_code_is_offered_only_where_it_is(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    offered = form_on(page_of(client, "/?step=agent"), "form.setup-agent")
    assert offered.select_one("input[value='claude-code']") is not None

    monkeypatch.setattr(setting_up, "claude_on_path", lambda: False)
    without = form_on(page_of(client, "/?step=agent"), "form.setup-agent")

    assert without.select_one("input[value='claude-code']") is None
    assert without.select_one("input[value='other']") is not None


def test_claude_code_chosen_is_given_this_kennis_by_its_full_path(
    client: TestClient, world: Recorded
) -> None:
    form = form_on(page_of(client, "/?step=agent"), "form.setup-agent")

    answer = submitted(client, form, agent="claude-code")

    assert answer.status_code == 200
    (added,) = [call for call in world.claude if call[:2] == ["mcp", "add"]]
    assert added[:6] == ["mcp", "add", "--scope", "user", "kennis", "--"]
    assert Path(added[6]).is_absolute()
    assert added[7] == "serve"


def test_another_agent_is_shown_what_to_paste(
    client: TestClient, world: Recorded
) -> None:
    form = form_on(page_of(client, "/?step=agent"), "form.setup-agent")

    answer = submitted(client, form, agent="other")

    pasted = BeautifulSoup(answer.text, "html.parser").select_one("pre code")
    assert pasted is not None
    assert '"mcpServers"' in pasted.get_text()
    assert '"serve"' in pasted.get_text()
    assert all(call[:2] != ["mcp", "add"] for call in world.claude)


def test_without_the_mcp_extra_no_agent_is_offered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setting_up, "mcp_installed", lambda: False)

    page = page_of(client, "/?step=agent")

    assert page.select_one("form.setup-agent") is None
    assert "kennis[mcp]" in page.get_text()


def test_the_last_step_describes_packs_and_context_and_opens_the_window(
    client: TestClient, world: Recorded, isolated: Path
) -> None:
    submitted(client, form_on(page_of(client, "/?step=corpus"), "form.setup-corpus"))
    page = page_of(client, "/?step=done")
    assert "kennis pack install" in page.get_text()
    assert "kennis context init" in page.get_text()

    answer = submitted(client, form_on(page, "form.setup-open"))

    assert answer.status_code == 303
    assert answer.location == SERVICE
    assert world.started == [isolated / "corpus"]
    assert world.done == 1


def test_kennis_gui_with_nothing_set_up_serves_the_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[bool] = []
    monkeypatch.setattr(
        setup_app,
        "serve_setup",
        lambda **keywords: served.append(bool(keywords["open_browser"])),
    )

    def no_service(*arguments: object, **keywords: object) -> object:
        raise AssertionError("the corpus service was started")

    monkeypatch.setattr("kennis.client.process.ensure_service", no_service)

    result = CliRunner().invoke(main, ["gui", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert served == [False]


def test_setting_up_is_needed_without_the_file_or_without_the_corpus(
    isolated: Path,
) -> None:
    assert setting_up.needs_setup()
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    # A corpus and no configuration file: still asked for (Brian, 2026-11-17).
    assert setting_up.needs_setup()
    assert CliRunner().invoke(main, ["config", "init", "--defaults"]).exit_code == 0

    assert not setting_up.needs_setup()
