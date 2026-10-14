"""`kennis gui`: open the graphical interface.

Thin, like `serve`. The command decides what a person is told and the
`gui` package does the work. The import stays inside the function so
that building the command tree for any other command does not import
fastapi and uvicorn.
"""

from __future__ import annotations

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand
from kennis.render.words import still_running_on_interrupt


@click.command(cls=KennisCommand, name="gui")
@click.option(
    "--no-browser",
    "no_browser",
    is_flag=True,
    help="Print the address and open nothing. For use over `ssh -L`.",
)
def gui_command(no_browser: bool) -> None:
    """Open kennis in a browser tab.

    The interface serves on the loopback interface only, on a port the
    operating system chooses, and needs a token that is minted for this
    run and printed below. Loopback is not private on a shared machine,
    which is what the token is for.
    """
    from kennis.gui.serve import run

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

    run(announce, open_browser=not no_browser, on_busy=warn)


__all__ = ["gui_command"]
