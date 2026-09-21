"""Running the git binary, under the external-process discipline.

Every call gets a timeout and a closed stdin. The second is not decoration:
git blocks on a terminal prompt for credentials or an editor, and a kennis
command that hangs with no output is the worst failure available. With stdin
closed it fails instead, which is something a caller can report.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kennis.engine.errors import GitUnavailable
from kennis.engine.history.git import GitResult, git, git_binary


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(["init"], cwd=tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def test_a_successful_call_reports_its_output(repository: Path):
    result = git(["rev-parse", "--is-inside-work-tree"], cwd=repository)

    assert result.ok
    assert result.stdout.strip() == "true"


def test_a_failing_call_is_a_result_and_not_an_exception(repository: Path):
    """A caller that can act on a failure gets to; a traceback from inside a
    subprocess wrapper is not something anyone can act on."""
    result = git(["cat-file", "-p", "nosuchobject"], cwd=repository)

    assert not result.ok
    assert result.status != 0
    assert result.stderr


def test_the_call_runs_with_stdin_closed(repository: Path):
    """Proven rather than asserted about: a command that reads stdin must see
    end-of-file immediately rather than waiting for a terminal."""
    result = git(["hash-object", "--stdin"], cwd=repository)

    assert result.ok
    # The hash of the empty object, which is what reading nothing produces.
    assert result.stdout.strip() == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_a_call_that_overruns_its_timeout_is_cancelled(
    repository: Path, monkeypatch: pytest.MonkeyPatch
):
    """One wedged call must not hang the whole command with no output.

    The timeout is provoked rather than waited for: what is under test is
    that an expired call becomes a reportable failure, not that any
    particular git command is slow. An earlier version of this test ran
    `hash-object --stdin-paths` with a tiny timeout and passed for the wrong
    reason - with stdin closed it reaches end-of-file and exits at once,
    which is the *other* property this module guarantees.
    """

    def expire(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="git", timeout=0.001)

    monkeypatch.setattr("subprocess.run", expire)

    result = git(["status"], cwd=repository, timeout=0.001)

    assert not result.ok
    assert "timed out" in result.stderr.lower()


def test_the_timeout_reaches_the_process(
    repository: Path, monkeypatch: pytest.MonkeyPatch
):
    """Every call gets one, and it is the caller's value rather than a
    default applied somewhere else."""
    seen: dict[str, object] = {}

    def record(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", record)
    git(["status"], cwd=repository, timeout=12.5)

    assert seen["timeout"] == 12.5
    assert seen["stdin"] is subprocess.DEVNULL


# ---------------------------------------------------------------------------
# The environment git runs in
# ---------------------------------------------------------------------------


def test_a_commit_works_with_no_user_identity_configured(tmp_path: Path):
    """A corpus commit is kennis's own, so it must not depend on the machine
    having a global `user.email` - and must not attribute a machine action to
    whichever person happens to be configured."""
    git(["init"], cwd=tmp_path)
    (tmp_path / "a.txt").write_text("body\n", encoding="utf-8")
    git(["add", "a.txt"], cwd=tmp_path)

    result = git(["commit", "-m", "test(scope): add a file"], cwd=tmp_path)

    assert result.ok, result.stderr


def test_git_is_never_left_waiting_for_a_credential_prompt(repository: Path):
    """`GIT_TERMINAL_PROMPT=0` turns a would-be prompt into a failure."""
    result = git(
        ["fetch", "https://example.invalid/nothing.git"], cwd=repository, timeout=15
    )

    assert not result.ok


# ---------------------------------------------------------------------------
# A missing binary
# ---------------------------------------------------------------------------


def test_a_missing_binary_is_reported_by_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(GitUnavailable):
        git_binary()


def test_the_missing_binary_message_names_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(GitUnavailable) as raised:
        git_binary()

    assert any("install" in note for note in raised.value.__notes__)


def test_a_missing_binary_is_raised_rather_than_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The one case that is not a result. Every other failure is git telling
    us something; this one is git not being there, and no caller can proceed
    past it."""
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(GitUnavailable):
        git(["status"], cwd=tmp_path)


def test_the_binary_is_found_when_it_is_present():
    assert Path(git_binary()).name.startswith("git")


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------


def test_lines_splits_output_and_drops_the_blank_tail(repository: Path):
    (repository / "a.txt").write_text("body\n", encoding="utf-8")
    git(["add", "a.txt"], cwd=repository)

    result = git(["diff", "--cached", "--name-only"], cwd=repository)

    assert result.lines() == ["a.txt"]


def test_an_empty_output_has_no_lines(repository: Path):
    assert git(["diff", "--name-only"], cwd=repository).lines() == []


def test_a_result_carries_the_command_that_produced_it(repository: Path):
    """A failure reported to a user has to say what was run, or the report is
    unactionable."""
    result = git(["cat-file", "-p", "nosuchobject"], cwd=repository)

    assert "cat-file" in " ".join(result.command)


def test_the_result_is_a_value_rather_than_a_process(repository: Path):
    result = git(["status", "--porcelain"], cwd=repository)

    assert isinstance(result, GitResult)
    assert not isinstance(result, subprocess.CompletedProcess)
