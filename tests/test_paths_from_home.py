"""A path under the person's home is shown from `~` (Brian, 2026-10-30).

"Just to make it less bloaty." Prose shortens; what a person or a program
feeds back does not: a remedy runs as printed and a quoted `'~/x'` does not
expand, and `kennis config path` is read by `$(...)`, after which a shell
expands no `~` either.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli import display
from kennis.cli.__main__ import main
from kennis.render.paths import from_home

HOME = "/home/brian"


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Created corpus at /home/brian/.local/share/kennis",
            "Created corpus at ~/.local/share/kennis",
        ),
        ("/home/brian", "~"),
        ("/home/brian/", "~/"),
        ("'/home/brian/x y' is not empty", "'~/x y' is not empty"),
        ("in /home/brian: nothing", "in ~: nothing"),
        ("(/home/brian/a, /home/brian/b)", "(~/a, ~/b)"),
    ],
)
def test_the_home_directory_becomes_a_tilde(text: str, expected: str):
    assert from_home(text, home=HOME) == expected


@pytest.mark.parametrize(
    "text",
    [
        "/home/brian2/notes",
        "/mnt/home/brian/notes",
        "/home/brianna",
        "a path relative to the corpus: notes/home/brian/x.md",
    ],
)
def test_a_path_that_only_contains_the_home_spelling_is_left_alone(text: str):
    assert from_home(text, home=HOME) == text


def test_a_windows_home_is_shortened_in_either_spelling():
    home = "C:\\Users\\Quickemu"

    assert (
        from_home("at C:\\Users\\Quickemu\\AppData\\Local\\kennis", home=home)
        == "at ~\\AppData\\Local\\kennis"
    )
    assert from_home("at C:/Users/Quickemu/PhD", home=home) == "at ~/PhD"


@pytest.mark.parametrize("home", ["/", ""])
def test_a_home_at_the_root_shortens_nothing(home: str):
    assert from_home("/etc/kennis", home=home) == "/etc/kennis"


# ---------------------------------------------------------------------------
# The display layer
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """`Path.home()` reads HOME on POSIX and USERPROFILE on Windows."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    display.set_verbosity()
    yield home
    display.set_verbosity()


def captured(action: Callable[[], None]) -> str:
    with display.console.capture() as out:
        action()
    return out.get()


@pytest.mark.parametrize(
    "printer",
    [
        lambda text: display.info(text),
        lambda text: display.success(text, lead="Created"),
        lambda text: display.warning(text),
        lambda text: display.error(text),
        lambda text: display.heading(text),
        lambda text: display.muted(text),
        lambda text: display.using(text),
        lambda text: display.operation("Created", text),
        lambda text: display.detail("+", text),
        lambda text: display.row("doc0000001", text),
        lambda text: display.setting_row(f"backup.folder = {text}"),
        lambda text: display.note(text),
        lambda text: display.failure(text),
    ],
)
def test_every_line_of_prose_shows_home_as_a_tilde(
    home: Path, printer: Callable[[str], None]
):
    shown = captured(lambda: printer(f"{home / 'corpus'} here"))

    assert str(home) not in shown
    assert f"~{os.sep}corpus here" in shown


def test_a_remedy_runs_as_printed(home: Path):
    command = f"kennis pack validate '{home / 'x y' / 'p.ken.yml'}'"

    assert command in captured(lambda: display.remedy(command))


def test_config_path_stays_absolute(home: Path):
    location = home / ".config" / "kennis" / "config.toml"

    assert captured(lambda: display.path(location)).strip() == str(location)


# ---------------------------------------------------------------------------
# A command, end to end
# ---------------------------------------------------------------------------


@pytest.fixture
def at_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(home / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(home / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(home / "corpus"))
    return home


def test_corpus_init_names_the_corpus_from_home(at_home: Path):
    result = CliRunner().invoke(main, ["corpus", "init"])

    assert result.exit_code == 0, result.output
    assert "Created corpus at ~" in result.output
    assert str(at_home) not in result.output


def test_an_error_and_its_log_hint_are_shown_from_home(at_home: Path):
    runner = CliRunner()
    assert runner.invoke(main, ["corpus", "init"]).exit_code == 0

    result = runner.invoke(main, ["corpus", "init"])

    assert result.exit_code != 0
    assert "is already a kennis corpus" in result.output
    assert "full detail in ~" in result.output
    assert str(at_home) not in result.output
