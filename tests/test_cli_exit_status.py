"""Each exit status kennis uses has a name, a meaning and one definition.

Brian, 2026-11-27: the statuses were literals scattered through the
command line - 1 in three places, 130 in two, 2 by click - and a sync gains
a new one, 3, for a run that did all it could and left papers that need
the reader's copy. `cli/exits.py::ExitStatus` names each; nothing raises
a bare number; the log says which status a command ended with, by name;
and the reference page's table, written by hand, is checked against it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.cli.exits import ExitStatus

SOURCE = Path(__file__).resolve().parents[1] / "src" / "kennis"
REFERENCE = Path(__file__).resolve().parents[1] / "docs" / "reference" / "cli.md"

# Written out by hand: comparing the page with the enum alone would pass
# for any enum the page was generated from (#373).
EXPECTED = {
    0: "DONE",
    1: "FAILED",
    2: "USAGE",
    3: "INCOMPLETE",
    130: "INTERRUPTED",
}


def test_the_statuses_are_the_ones_agreed():
    assert {status.value: status.name for status in ExitStatus} == EXPECTED


def _is_an_exit(call: ast.Call) -> bool:
    match call.func:
        case ast.Name(id="SystemExit" | "exit"):
            return True
        case ast.Attribute(value=ast.Name(id="sys" | "click" | "ctx"), attr="exit"):
            return True
        case _:
            return False


def _is_a_bare_exit(node: ast.AST) -> bool:
    """`SystemExit(1)`, `sys.exit(130)` and the like."""
    return (
        isinstance(node, ast.Call)
        and _is_an_exit(node)
        and any(
            isinstance(argument, ast.Constant) and isinstance(argument.value, int)
            for argument in node.args
        )
    )


def _is_a_bare_exit_code(node: ast.AST) -> bool:
    """`exit_code = 130`, as a click exception's class states its status."""
    return (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "exit_code"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
    )


def test_no_exit_in_the_package_is_given_a_bare_number():
    """The syntax tree, not the text, so a comment quoting `SystemExit(1)`
    cannot satisfy or trip it."""
    bare: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if _is_a_bare_exit(node) or _is_a_bare_exit_code(node):
                bare.append(f"{path.relative_to(SOURCE)}:{node.lineno}")
    assert bare == []


def test_the_reference_page_lists_every_status():
    text = REFERENCE.read_text(encoding="utf-8")
    section = text.split("## Exit status", 1)[1]
    rows = re.findall(r"^\| `?(\d+)`? \| `?([A-Z]+)`? \|", section, re.MULTILINE)
    assert {int(value): name for value, name in rows} == EXPECTED


@pytest.fixture
def logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    return tmp_path / "state" / "kennis.log"


def test_a_refusal_is_logged_by_its_status(logged: Path):
    """No corpus: every command that needs one refuses."""
    result = CliRunner().invoke(main, ["corpus", "list"])

    assert result.exit_code == ExitStatus.FAILED
    assert "exit FAILED (1)" in logged.read_text(encoding="utf-8")


def test_a_usage_error_is_logged_by_its_status(logged: Path):
    result = CliRunner().invoke(main, ["corpus", "list", "--no-such-option"])

    assert result.exit_code == ExitStatus.USAGE
    assert "exit USAGE (2)" in logged.read_text(encoding="utf-8")


def test_a_command_that_ran_to_its_end_logs_no_status(logged: Path):
    result = CliRunner().invoke(main, ["corpus", "init"])

    assert result.exit_code == ExitStatus.DONE, result.output
    assert re.search(r"exit [A-Z]+ \(\d+\)", logged.read_text(encoding="utf-8")) is None
