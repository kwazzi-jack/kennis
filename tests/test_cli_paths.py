"""Arguments a person typed, anchored where they typed them (14c).

The service reads files in its own process, whose directory is not the
person's, so a command makes a relative path or pattern absolute before
sending it. What is not a path - an arXiv identifier, a DOI, an address -
crosses as typed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.cli.paths import anchored


@pytest.fixture
def here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "one.md").write_text("# One\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_relative_path_that_exists_is_made_absolute(here: Path):
    assert anchored(["sources/one.md"]) == [str(here / "sources" / "one.md")]


def test_a_relative_directory_is_made_absolute(here: Path):
    assert anchored(["sources"]) == [str(here / "sources")]


def test_a_relative_pattern_is_anchored_here(here: Path):
    assert anchored(["sources/*.md"]) == [str(here / "sources" / "*.md")]


@pytest.mark.parametrize(
    "typed",
    [
        "2409.19750",
        "arXiv:2409.19750",
        "10.1093/mnras/stab1234",
        "https://example.org/docs/index.html?page=2",
        "https://docs.example.org/*",
        "sources/absent.md",
    ],
)
def test_what_is_not_a_path_here_crosses_as_typed(here: Path, typed: str):
    """An address keeps its `?` and `*`; a missing file stays as typed so
    the add's own refusal names it as the person wrote it."""
    assert anchored([typed]) == [typed]


def test_an_absolute_path_is_left_alone(here: Path):
    absolute = str(here / "sources" / "one.md")

    assert anchored([absolute]) == [absolute]


def test_corpus_add_sends_its_paths_anchored(
    here: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The in-process service shares this process's directory, so a relative
    path would work here and fail in a real service; what is sent is what
    has to be absolute."""
    from click.testing import CliRunner

    import kennis.cli.commands.corpus as corpus_command
    from kennis.cli.__main__ import main
    from kennis.client import api

    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    sent: list[list[str]] = []
    real = api.add

    def recording(
        corpus_root: Path,
        destination: str,
        identifiers: list[str],
        *rest: object,
        **named: object,
    ) -> object:
        sent.append(list(identifiers))
        return real(corpus_root, destination, identifiers, *rest, **named)

    monkeypatch.setattr(corpus_command.api, "add", recording)

    result = CliRunner().invoke(main, ["corpus", "add", "-n", "sources/one.md"])

    assert result.exit_code == 0, result.output
    assert sent == [[str(here / "sources" / "one.md")]]
