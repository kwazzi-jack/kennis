"""A `kennis://` link the command line prints is a hyperlink to itself
(Brian, 2026-11-06).

The text shown is the link, so it can be copied and read anywhere; on a
terminal it is also an OSC 8 hyperlink whose target is that same link, and
it is drawn as a link (underlined), because a terminal shows a hyperlink
only on hover and a dim line read as plain text. Where the output is not a
terminal - a pipe, a file, the baselines - only the text is written.
"""

from __future__ import annotations

import ast
import io
import re
from pathlib import Path

import pytest
from rich.console import Console

from kennis.cli import display

LINK = "kennis://context/tron/2?path=notes%2Fa+b.md"

# OSC 8: ESC ] 8 ; params ; URI ST, where ST is ESC \ or BEL.
_OPENS = re.compile(r"\x1b\]8;[^;]*;(?P<target>[^\x1b\x07]*)(?:\x1b\\|\x07)")
_UNDERLINE = re.compile(r"\x1b\[(?:[0-9]+;)*4(?:;[0-9]+)*m")


def printed_on(
    monkeypatch: pytest.MonkeyPatch, *, terminal: bool, write: object
) -> str:
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        theme=display._THEME,
        highlight=False,
        force_terminal=terminal,
        # A terminal that can show a link: left to detection, rich takes a
        # Windows runner, which has no console, for a legacy one and drops
        # every OSC 8 link, as it should on a console that cannot draw one.
        legacy_windows=False,
        color_system="standard" if terminal else None,
        width=200,
    )
    monkeypatch.setattr(display, "console", console)
    assert callable(write)
    write()
    return buffer.getvalue()


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda: display.hit_link(LINK), id="search"),
        pytest.param(lambda: display.detail_link("+", LINK), id="cite"),
    ],
)
def test_a_link_is_a_hyperlink_to_itself_and_looks_like_one(
    monkeypatch: pytest.MonkeyPatch, write: object
):
    shown = printed_on(monkeypatch, terminal=True, write=write)

    targets = [match.group("target") for match in _OPENS.finditer(shown)]
    assert LINK in targets
    visible = re.sub(r"\x1b\[[0-9;]*m", "", _OPENS.sub("", shown))
    assert LINK in visible
    assert _UNDERLINE.search(shown) is not None


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda: display.hit_link(LINK), id="search"),
        pytest.param(lambda: display.detail_link("+", LINK), id="cite"),
    ],
)
def test_off_a_terminal_only_the_link_s_text_is_written(
    monkeypatch: pytest.MonkeyPatch, write: object
):
    shown = printed_on(monkeypatch, terminal=False, write=write)

    assert "\x1b" not in shown
    assert LINK in shown


def _builds_a_console(statement: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"Console", "_BesideTheBar"}
        for node in ast.walk(statement)
    )


def _turns_on_escapes(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.If)
        and ast.unparse(statement.test) == "sys.platform == 'win32'"
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "just_fix_windows_console"
            for node in ast.walk(statement)
        )
    )


def test_a_windows_console_processes_escapes_before_any_console_is_built():
    """rich reads a Windows console's escape-sequence mode once, when a
    `Console` is built, and never turns it on; read as off, the console is
    taken for a legacy one and every hyperlink is dropped. So the mode is
    turned on at module level before the first console exists. No test can
    show a Windows console here (the runner has none), so this is ordering.
    """
    tree = ast.parse(Path(display.__file__).read_text(encoding="utf-8"))
    statements = list(tree.body)
    first_console = next(
        index
        for index, statement in enumerate(statements)
        if _builds_a_console(statement)
    )
    turned_on = [
        index
        for index, statement in enumerate(statements)
        if _turns_on_escapes(statement)
    ]

    assert turned_on, "display.py never turns on a Windows console's escapes"
    assert turned_on[0] < first_console
