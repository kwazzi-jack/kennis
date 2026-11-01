"""`kennis open` and `kennis link`: a cited passage, opened in the window.

A `kennis://` link names a document and a chunk and nothing about the
service, whose address and token change with every start (#569); `kennis
open` asks the service running now. `kennis link register` makes this
account's desktop run `kennis open` for a clicked link (#8, #594).
"""

from __future__ import annotations

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES


@click.command(cls=KennisCommand, name="open")
@click.argument("target", metavar="LINK_OR_HANDLE")
@click.option(
    "--chunk",
    type=click.IntRange(min=0),
    default=None,
    help="Mark this chunk, as a search hit's `chunk=` gives it. A link names its own.",
)
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three collections by default.",
)
@click.option(
    "--no-browser",
    "no_browser",
    is_flag=True,
    help="Print the address and open nothing.",
)
def open_command(
    target: str, chunk: int | None, collection: str | None, no_browser: bool
) -> None:
    """Open a document in the kennis window, at a chunk.

    `LINK_OR_HANDLE` is a `kennis://open/<document>/<chunk>` link, as a
    citation carries, or anything `kennis read` takes: an identifier, a
    title, a citekey, a DOI. The service is started if it is not running.
    """
    from kennis import __version__
    from kennis.client.process import ensure_service
    from kennis.gui.browser import open_quietly
    from kennis.links import is_a_link, target_of, window_address
    from kennis.render.words import describe_document, waiting_for_another_version

    handle = target
    if is_a_link(target):
        if chunk is not None:
            raise display.CliError(
                "a link names its own chunk; drop --chunk, or give a handle with it"
            )
        linked = target_of(target)
        handle, chunk = linked.document_id, linked.chunk
    corpus_root = existing_corpus().corpus_root

    def warn(version: str) -> None:
        display.warning(waiting_for_another_version(version, __version__))

    record = ensure_service(corpus_root, on_waiting=warn)
    found = api.found(corpus_root, handle, collection)
    address = window_address(
        record.address, found.collection, found.document.id, chunk, record.token
    )
    display.operation(
        "Showing" if no_browser else "Opened",
        describe_document(found.collection, found.document, corpus_root),
    )
    display.detail("+", address)
    if not no_browser:
        open_quietly(address)


@click.group(name="link", cls=KennisGroup)
def link_group() -> None:
    """Whether a clicked kennis:// link opens kennis, for this account."""


@link_group.command(name="register")
def register_command() -> None:
    """Make a clicked kennis:// link open the kennis window.

    On Linux, a desktop entry made the default for the scheme; on Windows, a
    URL protocol in this account's registry. It runs this installation of
    kennis by its full path, so register again after moving it, and run
    `kennis link remove` before uninstalling, which removes nothing itself.
    """
    from kennis.engine.scheme import register

    registration = register()
    display.operation("Registered", "kennis:// links for this account")
    for place in registration.written:
        display.detail("+", place)


@link_group.command(name="remove")
def remove_command() -> None:
    """Undo `kennis link register`. A kennis:// handler that another program
    registered is left alone."""
    from kennis.engine.scheme import remove

    removal = remove()
    if not removal.removed:
        display.operation("Unchanged", "no kennis:// registration of kennis's own")
        return
    display.operation("Removed", "the kennis:// registration")
    for place in removal.removed:
        display.detail("-", place)


__all__ = ["link_group", "open_command"]
