"""`kennis setup`: the settings, the corpus and an agent, in one walk
(#682, sketch 2026-11-17-setup-wizard, unit 1).

Each step is skipped when it is already done, and says so. Packs and a
project's context are described at the end, never offered (Brian,
2026-11-17).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis import setting_up
from kennis.cli.__main__ import main


def through_the_settings() -> str:
    """A return for each settings question the walk asks, accepting what
    each offers: as many as the catalogue has, not a guess, since a spare
    return would answer the next question with its default."""
    from kennis.engine.setup import questions_for

    return "\n" * len(questions_for({}))


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    return tmp_path


class FakeClaude:
    """`claude`, as `setting_up.claude_code` runs it: each call's arguments
    kept, `mcp get kennis` answering as registered or not."""

    def __init__(self, *, registered: bool) -> None:
        self.registered = registered
        self.calls: list[list[str]] = []

    def __call__(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        asked = arguments[:2] == ["mcp", "get"]
        code = 1 if asked and not self.registered else 0
        return subprocess.CompletedProcess(["claude", *arguments], code, "", "")


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    fake = FakeClaude(registered=False)
    monkeypatch.setattr(setting_up, "claude_code", fake)
    monkeypatch.setattr(setting_up, "claude_on_path", lambda: True)
    monkeypatch.setattr(setting_up, "mcp_installed", lambda: True)
    return fake


def walk(answers: str) -> str:
    result = CliRunner().invoke(main, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    return result.output


def test_a_fresh_setup_writes_the_settings_and_makes_the_corpus(
    isolated: Path, claude: FakeClaude
) -> None:
    said = walk(through_the_settings() + "none\n")

    assert (isolated / "config" / "config.toml").is_file()
    assert (isolated / "corpus" / ".git").is_dir()
    # "none" for the agent: `claude` is asked nothing that changes it.
    assert all(call[:2] != ["mcp", "add"] for call in claude.calls)
    assert "kennis gui" in said


def test_the_end_describes_packs_and_a_project_s_context_and_offers_neither(
    claude: FakeClaude,
) -> None:
    said = walk(through_the_settings() + "none\n")

    assert "kennis pack install" in said
    assert "kennis context init" in said


def test_run_again_it_keeps_the_settings_and_the_corpus_and_says_so(
    isolated: Path, claude: FakeClaude
) -> None:
    walk(through_the_settings() + "none\n")
    written = (isolated / "config" / "config.toml").read_bytes()

    # Return to "change the settings?", whose default is No; then "none".
    said = walk("\nnone\n")

    assert (isolated / "config" / "config.toml").read_bytes() == written
    assert "already" in said
    assert str(isolated / "corpus") in said


def test_claude_code_chosen_is_given_this_kennis_by_its_full_path(
    claude: FakeClaude,
) -> None:
    walk(through_the_settings() + "claude-code\n")

    (added,) = [call for call in claude.calls if call[:2] == ["mcp", "add"]]
    assert added[:6] == ["mcp", "add", "--scope", "user", "kennis", "--"]
    command, argument = added[6:]
    assert Path(command).is_absolute()
    assert Path(command).name.startswith("kennis")
    assert argument == "serve"


def test_claude_code_already_serving_kennis_is_left_as_it_is(
    claude: FakeClaude,
) -> None:
    claude.registered = True

    said = walk(through_the_settings() + "claude-code\n")

    assert all(call[:2] != ["mcp", "add"] for call in claude.calls)
    assert "already" in said


def test_another_agent_is_shown_what_to_paste(claude: FakeClaude) -> None:
    said = walk(through_the_settings() + "other\n")

    assert '"mcpServers"' in said
    assert '"serve"' in said
    assert all(call[:2] != ["mcp", "add"] for call in claude.calls)


def test_without_the_mcp_extra_no_agent_is_offered(
    claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setting_up, "mcp_installed", lambda: False)

    # No answer for the agent: the question is not asked.
    said = walk(through_the_settings())

    assert "kennis[mcp]" in said
    assert claude.calls == []


def test_without_claude_code_only_another_agent_or_none_is_offered(
    claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setting_up, "claude_on_path", lambda: False)

    result = CliRunner().invoke(
        main, ["setup"], input=through_the_settings() + "claude-code\nnone\n"
    )

    assert result.exit_code == 0, result.output
    assert claude.calls == []
