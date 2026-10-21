"""`kennis backup`: write, check and restore the encrypted archive.

Its own group because `kennis corpus restore` already restores one
document from history, which is a different thing with the same verb.
The password is asked for each time, with hidden input, and is never
stored, logged or passed on a command line, where it would sit in the
shell's history.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisGroup
from kennis.cli.sink import DisplaySink, say_waiting
from kennis.client import api
from kennis.context import existing_corpus, resolve_context

if TYPE_CHECKING:
    pass

_TO_HELP = "This folder instead of backup.folder, for this run only."


@click.group(name="backup", cls=KennisGroup)
def backup_group() -> None:
    """Write, check and restore an encrypted backup of the corpus."""


@backup_group.command(name="create")
@click.option("--to", "folder", type=click.Path(path_type=Path), help=_TO_HELP)
def create_command(folder: Path | None) -> None:
    """Write the corpus and its history to one encrypted .7z file.

    Everything but the working copy of the index, which the history
    holds and a restore checks out again. The file is tested with the
    password before it replaces the last backup, so a failed run never
    destroys a good one.
    """
    from kennis.render.backup import BACKUP_PASSWORD_PROMPT, describe_written

    chosen = _folder(folder)
    context = existing_corpus()
    password = click.prompt(
        BACKUP_PASSWORD_PROMPT, hide_input=True, confirmation_prompt=True
    )
    with DisplaySink() as shown:
        report = api.back_up(
            context.corpus_root, chosen, password, events=shown, on_waiting=say_waiting
        ).result
    # The service was sent the folder made absolute; the report names it
    # as the person did, which is what `backup check --to` will be given.
    report = replace(report, path=chosen / report.path.name)
    display.operation(
        "Backed up", describe_written(report), elapsed=report.elapsed_seconds
    )


@backup_group.command(name="check")
@click.option("--to", "folder", type=click.Path(path_type=Path), help=_TO_HELP)
@click.option(
    "--test",
    is_flag=True,
    help="Ask for the password and test every file in the backup.",
)
def check_command(folder: Path | None, test: bool) -> None:
    """Whether the folder is usable, and when the backup was last written."""
    from kennis.engine.backup import check_backup
    from kennis.engine.errors import BackupUnreadable
    from kennis.render.backup import (
        BACKUP_PASSWORD_PROMPT,
        describe_archive,
        describe_folder,
        describe_verified,
    )

    chosen = _folder(folder)
    password = click.prompt(BACKUP_PASSWORD_PROMPT, hide_input=True) if test else None
    checked = check_backup(chosen, password)
    display.plain(describe_folder(checked))
    display.plain(describe_archive(checked))
    if checked.verified is None:
        return
    if not checked.verified:
        raise BackupUnreadable()
    display.operation("Tested", describe_verified(checked.verified))


@backup_group.command(name="restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--to",
    "target",
    type=click.Path(path_type=Path),
    help="Where the corpus is restored. The configured corpus by default.",
)
def restore_command(archive: Path, target: Path | None) -> None:
    """Unpack a backup as the corpus, refusing to write over one."""
    from kennis.engine.backup import restore_backup
    from kennis.render.backup import BACKUP_PASSWORD_PROMPT, describe_restored

    destination = target or resolve_context().corpus_root
    password = click.prompt(BACKUP_PASSWORD_PROMPT, hide_input=True)
    report = restore_backup(archive, destination, password)
    display.operation("Restored", describe_restored(report))
    display.next_step("kennis corpus index", note="before searching it")


def _folder(given: Path | None) -> Path:
    from kennis.engine.backup import SET_FOLDER_COMMAND
    from kennis.engine.errors import BackupRefused
    from kennis.engine.settings import load_settings
    from kennis.render.backup import NO_BACKUP_FOLDER

    if given is not None:
        return given.expanduser()
    configured = load_settings().backup.folder
    if not configured:
        raise BackupRefused(NO_BACKUP_FOLDER, resolution=SET_FOLDER_COMMAND)
    return Path(configured).expanduser()


__all__ = ["backup_group"]
