"""The commands attached to the `kennis` group by `__main__`."""

from __future__ import annotations

from kennis.cli.commands.config import config_group
from kennis.cli.commands.context import context_group
from kennis.cli.commands.corpus import corpus_group
from kennis.cli.commands.gui import gui_command
from kennis.cli.commands.pack import pack_group
from kennis.cli.commands.remember import remember_command
from kennis.cli.commands.search import read_command, search_command
from kennis.cli.commands.serve import serve_command

__all__ = [
    "config_group",
    "context_group",
    "corpus_group",
    "gui_command",
    "pack_group",
    "read_command",
    "remember_command",
    "search_command",
    "serve_command",
]
