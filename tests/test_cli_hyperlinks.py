"""A `kennis://` link the command line prints is a hyperlink to itself
(Brian, 2026-11-06).

The text shown is the link, so it can be copied and read anywhere; on a
terminal it is also an OSC 8 hyperlink whose target is that same link, and
it is drawn as a link (underlined), because a terminal shows a hyperlink
only on hover and a dim line read as plain text. Where the output is not a
terminal - a pipe, a file, the baselines - only the text is written.
"""

from __future__ import annotations

import io
import re

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
