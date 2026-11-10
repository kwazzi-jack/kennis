"""What a command's help says, across every command kennis has."""

from __future__ import annotations

from collections.abc import Iterator

import click

from kennis.cli.__main__ import main


def every_command(
    command: click.Command, parent: click.Context | None = None
) -> Iterator[tuple[str, click.Command]]:
    name = command.name if parent is not None else "kennis"
    context = click.Context(command, info_name=name, parent=parent)
    yield context.command_path, command
    if isinstance(command, click.Group):
        for name in command.list_commands(context):
            child = command.get_command(context, name)
            if child is not None:
                yield from every_command(child, context)


def test_the_walk_reaches_nested_commands() -> None:
    """The assertion below means nothing if the walk stops at the top."""
    paths = {path for path, _ in every_command(main)}

    assert "kennis context status" in paths
    assert len(paths) > 40


def test_no_help_names_the_engine_state_in_step() -> None:
    """A current index is "up to date" wherever a reader sees it; "in step"
    is the engine's name for the state (#645)."""
    saying_it = [
        path
        for path, command in every_command(main)
        if "in step" in f"{command.help or ''} {command.short_help or ''}"
    ]

    assert saying_it == []
