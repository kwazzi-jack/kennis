"""A project's bundle is the service's to act on, and a service owns a
corpus, so with no corpus a bundle command is refused (14e, #519).

There is no second path that acts in the command's own process: every
command below would need one, and keeping it is what milestone 14 set out
to end. The refusal names the command that makes a corpus, which is
offline and instant.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=root,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize(
    "arguments",
    [
        ["context", "init"],
        ["context", "index"],
        ["context", "sync"],
        ["context", "status"],
        ["context", "packs"],
        ["context", "reset", "-y"],
        ["remember", "--context", "A note."],
        ["search", "anything"],
    ],
    ids=lambda arguments: " ".join(arguments[:2]),
)
def test_a_bundle_command_with_no_corpus_names_corpus_init(
    project: Path, arguments: list[str]
):
    answered = CliRunner().invoke(main, arguments)

    assert answered.exit_code != 0, answered.output
    assert "kennis corpus init" in answered.output
    # Refused before anything was written into the person's repository.
    assert not (project / ".context").exists()
