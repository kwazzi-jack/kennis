"""`kennis gui`: open the window onto the corpus's service.

Thin. The window is served by the service that owns the corpus (milestone
14), started here if none runs, so this opens an address and returns: the
service outlives the command, stops by itself when idle, and serves the
same window to every tab.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand
from kennis.render.words import (
    SERVICE_STOPS_ITSELF,
    TOKEN_IN_THE_ADDRESS,
    waiting_for_another_version,
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
    help="Stop the kennis service and start another before opening.",
)
def gui_command(no_browser: bool, replace: bool) -> None:
    """Open kennis in a browser tab.

    The window is served by the kennis service for this corpus, on the
    loopback interface only, on a port the operating system chooses, with a
    token in the address. Loopback is not private on a shared machine, which
    is what the token is for. The service is started if it is not running.
    """
    from kennis.client.process import ensure_service, stop_service
    from kennis.context import existing_corpus
    from kennis.engine.context.bundle import find_bundle
    from kennis.gui.browser import open_quietly
    from kennis.protocol.record import find_service

    corpus_root = existing_corpus().corpus_root
    if replace:
        running = find_service(corpus_root)
        if running is not None:
            stop_service(corpus_root, running)

    def warn(version: str) -> None:
        display.warning(waiting_for_another_version(version))

    record = ensure_service(corpus_root, on_waiting=warn)
    # The project is found here, where the person typed the command, and
    # named in the address: the service serves every directory (#508).
    # Empty outside a project, so the tab does not keep an earlier one.
    bundle = find_bundle(Path.cwd())
    address = f"{record.address}?" + urlencode(
        {"token": record.token, "bundle": "" if bundle is None else str(bundle)}
    )
    # Said before the browser is asked: `webbrowser.open` can fail
    # silently, and then this line is the only way in.
    display.operation("Serving" if no_browser else "Opened", "the kennis window")
    display.detail("+", address)
    display.guidance(TOKEN_IN_THE_ADDRESS)
    display.guidance(SERVICE_STOPS_ITSELF)
    if not no_browser:
        open_quietly(address)


__all__ = ["gui_command"]
