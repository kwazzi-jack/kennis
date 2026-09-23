"""The commands attached to the `kennis` group by `__main__`."""

from __future__ import annotations

from kennis.cli.commands.config import config_group
from kennis.cli.commands.corpus import corpus_group
from kennis.cli.commands.remember import remember_command
from kennis.cli.commands.search import read_command, search_command

__all__ = [
    "config_group",
    "corpus_group",
    "read_command",
    "remember_command",
    "search_command",
]
