"""`kennis tag`, `kennis untag` and `kennis tags` (#625).

A passage is named as `kennis cite` takes it - a search hit's `id=X
chunk=N` or `path=P chunk=N`, a `kennis://` link, or any handle for a whole
document - and the names are one argument, comma-separated, because a tag
holds no comma or space. The service writes the corpus's `tags.yml` and
commits it, and a project's `.context/tags.yml`, which it leaves for the
person to commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError

if TYPE_CHECKING:
    from kennis.tagging import Tagged, TagListing


@click.command(cls=KennisCommand, name="tag")
@click.argument("names", metavar="NAMES")
@click.argument("passages", nargs=-1, metavar="[PASSAGE]...")
@click.option(
    "--colour",
    metavar="COLOUR",
    help="Draw these tags in COLOUR in the window: red, orange, yellow, green, "
    "teal, blue, purple or pink; auto goes back to the colour derived from "
    "the name. With no PASSAGE, only the colour is set.",
)
def tag_command(names: str, passages: tuple[str, ...], colour: str | None) -> None:
    """Tag passages or documents with each of `NAMES`.

    `NAMES` is one or more tags separated by commas, such as
    `calibration,to-cite`; a tag is one word, folded to lowercase. A
    `PASSAGE` is named as `kennis cite` takes it: a hit's `id=X chunk=N` or
    `path=P chunk=N`, a `kennis://` link, or a handle for the whole document.
    """
    if not passages and colour is None:
        raise click.UsageError("name at least one PASSAGE, or give --colour")
    if passages:
        _changed(names, passages, remove=False)
    if colour is not None:
        _coloured(names, colour)


@click.command(cls=KennisCommand, name="untag")
@click.argument("names", metavar="NAMES")
@click.argument("passages", nargs=-1, required=True, metavar="PASSAGE...")
def untag_command(names: str, passages: tuple[str, ...]) -> None:
    """Take each of `NAMES` from passages or documents, named as for `kennis tag`."""
    _changed(names, passages, remove=True)


@click.command(cls=KennisCommand, name="tags")
@click.argument("name", required=False)
def tags_command(name: str | None) -> None:
    """List every tag and how much it holds, or what one tag holds.

    Run in a project, its tags are listed beside the corpus's. A passage
    whose words are no longer in its document is said to be detached, with
    the command that removes its tag.
    """
    from pathlib import Path

    from kennis.engine.context.bundle import find_bundle
    from kennis.engine.tags import tag_name

    listed = api.tags(existing_corpus().corpus_root, find_bundle(Path.cwd()))
    if name is None:
        _all_tags(listed)
        return
    wanted = tag_name(name)
    for listing in listed:
        if listing.name == wanted:
            _one_tag(listing)
            return
    raise KennisError(f"nothing is tagged {wanted}", resolution="kennis tags")


def _changed(names: str, passages: tuple[str, ...], *, remove: bool) -> None:
    from kennis.cli.commands.cite import requests_from
    from kennis.engine.tags import split_tag_names

    folded = split_tag_names(names)
    requests = requests_from(passages)
    root = existing_corpus().corpus_root
    call = api.untag if remove else api.tag
    tagged = call(root, requests, folded).result
    _report(tagged, folded, remove=remove)


def _coloured(names: str, colour: str) -> None:
    from pathlib import Path

    from kennis.engine.context.bundle import find_bundle
    from kennis.engine.tags import split_tag_names
    from kennis.render.tags import coloured

    asked = colour.strip().lower()
    bundle = find_bundle(Path.cwd())
    done = api.colour_tags(
        existing_corpus().corpus_root,
        split_tag_names(names),
        None if asked == "auto" else asked,
        [] if bundle is None else [bundle],
    ).result
    for name in done.names:
        display.operation("Coloured", coloured(name, done.shown[name], done.colour))


def _report(tagged: Tagged, names: tuple[str, ...], *, remove: bool) -> None:
    from kennis.render.tags import already_tagged, joined_names, not_tagged

    for refusal in tagged.refused:
        display.failure(f"{refusal.handle}: {refusal.message}")
        if refusal.resolution is not None:
            display.remedy(refusal.resolution)
    if tagged.refused:
        raise display.CliError(
            f"{len(tagged.refused)} passages could not be found, so nothing was "
            f"{'untagged' if remove else 'tagged'}"
        )
    verb = "Untagged" if remove else "Tagged"
    for change in tagged.changes:
        shown = change.title or change.handle
        if change.changed:
            display.operation(verb, f"{shown}: {joined_names(change.changed)}")
        else:
            display.operation("Unchanged", shown, style="muted")
        display.detail_link("-" if remove else "+", change.link)
        if change.unchanged:
            said = not_tagged if remove else already_tagged
            display.muted(said(change.unchanged), indent="    ")
    del names


def _all_tags(listed: list[TagListing]) -> None:
    if not listed:
        display.muted("Nothing is tagged yet; tag a search hit with kennis tag.")
        return
    for listing in listed:
        display.row(listing.name, str(len(listing.targets)))


def _one_tag(listing: TagListing) -> None:
    from kennis.render.tags import target_state, target_title, untag_command
    from kennis.tagging import DETACHED, MISSING

    display.heading(listing.name)
    for target in listing.targets:
        display.hit(target_title(target))
        display.hit_link(target.link)
        if target.quote is not None:
            display.hit_detail(f'"{target.quote}"')
        trouble = target_state(target)
        if trouble is not None:
            display.note(trouble)
        if target.state in (DETACHED, MISSING):
            display.remedy(untag_command(listing.name, target))


__all__ = ["tag_command", "tags_command", "untag_command"]
