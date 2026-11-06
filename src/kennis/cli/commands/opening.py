"""`kennis open` and `kennis link`: a cited passage, opened in the window.

A `kennis://` link names a document and a chunk and nothing about the
service, whose address and token change with every start (#569); `kennis
open` asks the service running now. `kennis link register` makes this
account's desktop run `kennis open` for a clicked link (#8, #594).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.corpus.schema import COLLECTION_NAMES

if TYPE_CHECKING:
    from pathlib import Path

    from kennis.links import ContextTarget
    from kennis.protocol.record import ServiceRecord


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

    `LINK_OR_HANDLE` is a `kennis://` link, as a citation or a search hit
    carries - to a corpus document, a project's context file or a pack's -
    or anything `kennis read` takes: an identifier, a title, a citekey, a
    DOI. The service is started if it is not running. A kennis window
    already open shows it; otherwise a browser tab opens.
    """
    from kennis import __version__
    from kennis.client.process import ensure_service
    from kennis.links import (
        LinkTarget,
        is_a_link,
        link_to,
        target_of,
        window_path,
        window_path_of,
    )
    from kennis.render.words import describe_document, waiting_for_another_version

    handle = target
    located = None
    if is_a_link(target):
        if chunk is not None:
            raise display.CliError(
                "a link names its own chunk; drop --chunk, or give a handle with it"
            )
        linked = target_of(target)
        if isinstance(linked, LinkTarget):
            handle, chunk = linked.document_id, linked.chunk
        else:
            located = linked
    corpus_root = existing_corpus().corpus_root

    def warn(version: str) -> None:
        display.warning(waiting_for_another_version(version, __version__))

    if located is not None:
        described = _checked(located)
        record = ensure_service(corpus_root, on_waiting=warn)
        _shown(
            corpus_root,
            record,
            target,
            window_path_of(located),
            described,
            no_browser=no_browser,
        )
        return
    record = ensure_service(corpus_root, on_waiting=warn)
    found = api.found(corpus_root, handle, collection)
    described = describe_document(found.collection, found.document, corpus_root)
    _shown(
        corpus_root,
        record,
        link_to(found.document.id, chunk),
        window_path(found.collection, found.document.id, chunk),
        described,
        collection=found.collection,
        no_browser=no_browser,
    )


def _checked(located: ContextTarget) -> str:
    """What a context link names, said as the report names it, once it is
    known to be there: checked here, where the list of projects and the
    bundle are."""
    from kennis.engine.context.bundle import BUNDLE_DIRNAME
    from kennis.engine.context.notes import bundle_documents
    from kennis.engine.context.projects import project_named

    project = project_named(located.project)
    held = {
        path.relative_to(project.bundle).as_posix()
        for path in bundle_documents(project.bundle)
    }
    if located.path not in held:
        raise display.CliError(
            f"'{located.path}' is not in the project {project.name}'s bundle"
        )
    return f"{project.name}/{BUNDLE_DIRNAME}/{located.path}"


def _shown(
    corpus_root: Path,
    record: ServiceRecord,
    link: str,
    window: str,
    described: str,
    *,
    collection: str | None = None,
    no_browser: bool,
) -> None:
    """Show the passage `link` names in the window already open, or in a
    new tab; `window` is its path there."""
    from kennis.gui.browser import open_quietly
    from kennis.links import window_address

    address = window_address(record.address, window, record.token)
    if no_browser:
        display.operation("Showing", described)
        display.detail("+", address)
        return
    # A window already open shows it, rather than a new tab each time
    # (Brian, 2026-11-01); a tab is opened only when none answers.
    if api.show_in_window(corpus_root, link, collection):
        display.operation("Opened", f"{described}, in the open window")
        display.detail("+", address)
        return
    display.operation("Opened", described)
    display.detail("+", address)
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
