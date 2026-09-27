"""`kennis gui`: open the graphical interface.

Thin, like `serve`. The command decides what a person is told and the
`gui` package does the work, and the import is deferred into the
function body so that building the command tree does not pull the
`gui` extra in - someone who installed kennis without it must still be
able to run every other command.
"""

from __future__ import annotations

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand


@click.command(cls=KennisCommand, name="gui")
@click.option(
    "--browser",
    "browser_only",
    is_flag=True,
    help="Open in a browser rather than a window. Works over `ssh -L`.",
)
def gui_command(browser_only: bool) -> None:
    """Open kennis in a window, or in a browser if there is no window.

    The interface serves on the loopback interface only, on a port the
    operating system chooses, and needs a token that is minted for this
    run and printed below. Loopback is not private on a shared machine,
    which is what the token is for.
    """
    from kennis.gui.serve import run

    def announce(url: str) -> None:
        # Said once the port is known and before the call blocks. In
        # browser mode `webbrowser.open` can fail silently - no browser,
        # no display, a headless session - and then this line is the
        # only way in.
        display.operation("Serving", "the kennis interface")
        display.detail("+", url)
        display.guidance("The token is in the address and lasts for this run only.")

    run(announce, browser_only=browser_only)


__all__ = ["gui_command"]
