"""`kennis gui`: open the graphical interface.

Thin, like `serve`. The command decides what a person is told and the
`gui` package does the work. The import stays inside the function so
that building the command tree for any other command does not import
fastapi and uvicorn.
"""

from __future__ import annotations

import sys

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand
from kennis.render.words import (
    OPEN_CHOICES,
    OPEN_OR_REPLACE,
    REPLACED_THE_WINDOW,
    still_running_on_interrupt,
    window_already_open,
)


@click.command(cls=KennisCommand, name="gui")
@click.option(
    "--no-browser",
    "no_browser",
    is_flag=True,
    help="Print the address and open nothing. For use over `ssh -L`.",
)
@click.option(
    "--replace",
    is_flag=True,
    help="Stop a kennis window that is already open, and open this one.",
)
def gui_command(no_browser: bool, replace: bool) -> None:
    """Open kennis in a browser tab.

    The interface serves on the loopback interface only, on a port the
    operating system chooses, and needs a token that is minted for this
    run and printed below. Loopback is not private on a shared machine,
    which is what the token is for.

    One window at a time: with one already open, this opens it, or with
    `--replace` stops it first. A terminal is asked which.
    """
    from kennis.gui import instance, serve

    window = instance.open_window()
    if window is not None:
        started = window.started.strftime("%Y-%m-%d %H:%M")
        display.warning(window_already_open(started, window.version))
        choice = "replace" if replace else _choice()
        if choice == "cancel":
            return
        if choice == "open":
            if no_browser:
                display.detail("+", window.address)
            else:
                serve.open_quietly(window.address)
            return
        instance.ask_to_quit(window)
        display.operation("Stopped", REPLACED_THE_WINDOW)

    def announce(url: str) -> None:
        # Said once the port is known and before the call blocks.
        # `webbrowser.open` can fail silently - no browser, no display,
        # a headless session - and then this line is the only way in.
        display.operation("Serving", "the kennis interface")
        display.detail("+", url)
        display.guidance("The token is in the address and lasts for this run only.")
        display.guidance("Stop it with Quit in the page, or Ctrl-C here.")

    def warn(kind: str) -> None:
        display.warning(still_running_on_interrupt(kind))

    serve.run(announce, open_browser=not no_browser, on_busy=warn)


def _asked_in_a_terminal() -> bool:
    """Whether a person is there to choose. A script or a pipe gets the
    window that is already open, which is what it most likely wanted."""
    return sys.stdin.isatty()


def _choice() -> str:
    if not _asked_in_a_terminal():
        return "open"
    return str(
        click.prompt(
            OPEN_OR_REPLACE,
            type=click.Choice(OPEN_CHOICES),
            default="open",
            show_choices=True,
        )
    )


__all__ = ["gui_command"]
