"""A line printed while a progress bar is live stays on the screen.

The bar is drawn on stderr by its own console and the report goes to
stdout through another. rich places a line above a live bar only when it is
printed through the bar's console, so a warning printed through the
report's console was written after the bar and erased by its next redraw,
leaving a frozen copy of the bar where the warning had been. Found on
Brian's machine: `kennis context index` lost "12 of 45 passages ... longer
than ... 512 tokens" that way.

What is asserted is the final screen, not the bytes: both consoles write
to one buffer, as stdout and stderr share one terminal, and the buffer is
replayed by a small emulator of the escape codes rich writes.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator

import pytest

from kennis.cli import display, sink
from kennis.engine.events import (
    Diagnostic,
    OperationFinished,
    PassagesCutShort,
    Progress,
    Severity,
)

_WIDTH = 100
_ESCAPE = re.compile(
    r"\x1b\](?:[^\x07\x1b]|\x1b(?!\\))*(?:\x07|\x1b\\)"  # OSC, such as a link
    r"|\x1b\[(?P<parameters>[0-9;?]*)(?P<final>[A-Za-z])"  # CSI
)


def final_screen(written: str) -> list[str]:
    """What a terminal shows after `written`, one string per row.

    Only what rich writes is understood: carriage return, line feed, cursor
    up (`A`), erase line (`K`); colours, cursor visibility and links are
    read and draw nothing.
    """
    rows: list[list[str]] = [[]]
    row = column = 0
    position = 0
    while position < len(written):
        escape = _ESCAPE.match(written, position)
        if escape is not None:
            position = escape.end()
            final = escape.group("final")
            if final == "A":
                row = max(0, row - int(escape.group("parameters") or "1"))
            elif final == "K":
                rows[row] = []
                column = 0 if escape.group("parameters") == "2" else column
            continue
        character = written[position]
        position += 1
        if character == "\r":
            column = 0
        elif character == "\n":
            row += 1
            column = 0
            while len(rows) <= row:
                rows.append([])
        else:
            line = rows[row]
            while len(line) < column:
                line.append(" ")
            if column < len(line):
                line[column] = character
            else:
                line.append(character)
            column += 1
    return ["".join(line).rstrip() for line in rows]


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> Iterator[io.StringIO]:
    """Every console of the display writing to one terminal-like buffer."""
    shared = io.StringIO()
    for one in (display.console, display.error_console, display._progress_console):
        monkeypatch.setattr(one, "_file", shared)
        monkeypatch.setattr(one, "_force_terminal", True)
        monkeypatch.setattr(one, "_width", _WIDTH)
        # Decided once when a console is made, so forcing the terminal
        # afterwards does not reach it, and a bar that is not interactive
        # draws nothing at all.
        monkeypatch.setattr(one, "is_interactive", True)
    monkeypatch.setattr(display, "_progress_wanted", True)
    monkeypatch.setattr(display, "_quiet", False)
    monkeypatch.setattr(display, "_messages", "all")
    monkeypatch.setattr(display, "_task_keys", None)
    assert display.progress_wanted(), "the fixture no longer draws a bar"
    assert display._progress_console.is_interactive, "the bar would draw nothing"
    yield shared


_CUT_SHORT = Diagnostic(
    severity=Severity.WARNING,
    detail=PassagesCutShort(
        model="BAAI/bge-small-en-v1.5",
        limit=512,
        count=12,
        total=45,
        shortened=False,
    ),
)


def test_a_warning_under_a_bar_stays_and_the_bar_leaves_nothing(
    terminal: io.StringIO,
) -> None:
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=0, total=45))
        shown.emit(_CUT_SHORT)
        shown.emit(Progress(operation="index", completed=45, total=45))
        shown.emit(OperationFinished(operation="index", elapsed_seconds=3.6))
    display.operation("Indexed", "1 document as 45 chunks")

    screen = [row for row in final_screen(terminal.getvalue()) if row]
    assert any("12 of 45 passages" in row for row in screen), screen
    assert not any("/45" in row or "Indexing" in row for row in screen), screen
    assert screen[-1].startswith("Indexed"), screen


def test_the_bar_is_drawn_again_under_the_line(terminal: io.StringIO) -> None:
    """Setting the bar aside must not end it: what is drawn after the line
    is the bar again, at its latest count, until it closes."""
    with sink.DisplaySink() as shown:
        shown.emit(Progress(operation="index", completed=3, total=45))
        shown.emit(_CUT_SHORT)
        screen = [row for row in final_screen(terminal.getvalue()) if row]
        warning = next(
            index for index, row in enumerate(screen) if "12 of 45 passages" in row
        )
        assert any("3/45" in row for row in screen[warning + 1 :]), screen
